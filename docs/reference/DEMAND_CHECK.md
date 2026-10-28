# Demand check: is it wanted, before anyone builds it

**In plain words.** Knos pays for work that is proven done. Before the work, a maker wants to know whether anyone
wants the thing at all.

Knos's demand check asks Qloo's taste data (who, where, rising or not, against which
rivals), makes the maker confirm every match Qloo proposes, writes the demand report into the Knos Record, and lets
buyers lock pre-orders for that exact report, held on Solana devnet until the proof passes.

A buyer agent ranks the products that
are not built yet against tastes the buyer chooses. The code is [`apps/wanted/`](../../apps/wanted).

Every Qloo result is aggregate taste, not a prediction about one person. A report is directional demand evidence,
not a sales forecast.

## The decision check (Qloo's harness first, since 22 Oct 2026)

`POST /api/check {idea, place?, leader?}` (web page, or `knos mcp` tool `knos_demand_check` with
`KNOS_MCP_TOOLS=demand`, which POSTs to the hosted app at `KNOS_WANTED_URL`).

Code: `apps/wanted/knos_wanted/check.py`
over `qloo_rest.py` (key in the request header only, from the server's environment; answers cached privately with
no time limit; at most 4 calls per second; a monthly budget, `QLOO_MONTHLY_BUDGET`, default 9,000 uncached calls).

It sends at most 1,500 calls on one UTC day (`DAY_CAP`), and none once Qloo's month has under 2,000 calls left (`MONTH_FLOOR`).

Each call goes first to Qloo's harness: one long-lived `qloo api mcp` process (`qloo_harness.py`), a surface the kit
supports. A call goes there only when every parameter it sends maps onto a harness tool's argument, so its answer is
the one REST gives (checked call by call on 22 Oct 2026: demographics, audiences, heatmap, places, search).

The other calls need a parameter the harness does not take (a popularity floor, a trend bias, diversification, a tag
filter). They go to the REST API as before. The trace page says, for every call, which surface answered it, and
`/api/status` counts the harness's answers.

| Step | Qloo call | Gives |
|---|---|---|
| closest products, leader | `/search` (key words only, typed by the idea's kind: brand, videogame, place, ...) + `/entities` | names, popularity; the leader = top match unless named |
| taste tags | `/v2/tags` (`filter.parents.types` = that kind) | the idea's tags |
| who | `/v2/insights` `filter.type=urn:demographics` | age and gender affinity |
| where | `/v2/insights` `filter.type=urn:entity:place` and `urn:heatmap`, `filter.location.query` = place (default United States) | named places and map hot spots |
| segments | `/v2/insights` `filter.type=urn:audience` | audience segments by affinity (`/v2/audiences` lists the same segments unranked) |
| rising or falling | `/v2/trending` (`filter.type`, `signal.interests.entities`, 12-week windows going back until Qloo has data) | weekly population percentile |
| vs the leader | `/v2/analysis/compare` (a = the idea's neighbours, b = the leader) | shared tags (overlap), whitespace |

Every number in the report carries `src`, the index of the call in `report.calls` that produced it.

**Decision rules** (`check.RULES`, deterministic; no language model decides).

Thresholds were set on Qloo's real
answers (16 Oct 2026: 15 cached audience answers and 10 calibration ideas) and why:

- **Relevance gate.** Content words = the idea minus filler ("all", "about", "the"), pitch words ("smart", "new") and
  instruction words ("ignore", "rules", "decision", "release", "funds"); kind words ("podcast", "bar", "game") pick the
  Qloo type but do not count as a match.

A Qloo product counts only when its name shares 2 content words with the
  idea, or 1 in the name and 1 more in its description or tags. None: REFUSE "no product in Qloo matches this idea".

Why: single-word name hits were namesakes ("Swimsuits For All" for "all", "Road & Track" for "tracks").

- **Clone gate.** The leader's name is in the idea with a clone phrase ("exactly like", "clone of", ...) or is the
  idea's whole subject: REFUSE "an existing product already owns this".
- **Leader check, never skipped.** Overlap = shared taste tags / the smaller side (compare, when both sides have >= 3
  distinct tags), else shared informative audience segments of the idea's other matches vs the leader's own.

No
  comparison possible: REFUSE ("an existing product already owns this" when the leader's popularity is >= 0.9, else
  "no leader comparison possible"). Overlap >= 85%: REFUSE "the incumbent already serves this taste", whatever the
  leader's popularity (a Korean BBQ idea once opened at 96% overlap with a 0.85-popularity incumbent).

Overlap 60-85% with a leader of popularity >= 0.95: REFUSE (owned). Why: matched
  leaders' popularity ran 0.43-1.0 (median about 0.95); compare returned <= 1 tag on one side for most brands.
- **Audience.** A segment is informative when its affinity is above 0.55.

Why: when Qloo has no signal it returns a
  list flat at exactly 0.5 (spread 0.0); entity signals gave 0.64-0.88; adding tag signals pushed whole lists down to
  0.17-0.29 (so tags are not used as audience signals).

Fewer than 3 informative segments of 6, or no demographics:
  REFUSE "audience too thin".

- **Stated audience.** "students", "seniors", "women", "men", "parents", ... are compared with Qloo's demographics:
  <= -0.3 REFUSE (contradiction, shown); between -0.3 and 0 the target is halved.
- **Trend.** The leader's weekly population percentile over the newest 12-week window that has data (Qloo's series
  ends 24 Jul 2026: shown as "data through").

Every series measured was flat (start = end, velocity 0), and places,
  podcasts and video games have none: the report and page then say "Qloo's trend data ends 2026-07-24 and shows no
  movement for these; not counted" (neither for nor against).

Falling (<= -0.02): REFUSE;
  rising (>= +0.02): target x 1.25.

- **Size.** target = round10(100 x (1 + 2 x strength) x (1 - overlap/2) x audience factor x trend factor), strength =
  mean of (affinity - 0.5) x 2 over the informative segments; clamped to 20..1000; reserve = ceil(target x (0.3 + 0.2 x
  overlap)) units pre-ordered before the maker is paid.

Campaign sizes from a published formula, not a sales forecast.
- **No Qloo.** No key, the budget spent, or an essential call failing (search, demographics, segments) after one retry
  without the optional location/tags: CANNOT_DECIDE "cannot decide: no Qloo evidence". A failed optional call is
  listed as missing evidence and not counted.

Qloo's error text is never shown; a refused (4xx) question is cached a
  day so repeats do not spend the budget.

**Paid on proof.** On an OPEN report a signed-in user pre-orders (`POST /api/preorder`): the app's demo devnet wallet
(demo buyer, test money) locks the units through `knos.ideas.commit` as one stage "milestone" (oracle `referee_pass`)
judged by a 2-of-3 panel on the knos_pay 0.3.34 test program `FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4`; the
payee is the maker's devnet wallet.

The panel's keys are held by the server (`KNOS_WANTED_REFEREE_KEYS`): one server is
not an independent panel, and the commitment says UNLISTED PANEL.

`POST /api/milestone {commitment, evidence_url}`:
code fetches the https page (public addresses only, no redirects, 512 KB, 10 s), requires the commitment's claim id on
it and the report's reserve to be met; then two referees sign PASS over the page's sha256 and the server releases.
Not verified: nothing is signed; `POST /api/refund` returns the money after the deadline.

Knos's fee is the payout line
of `config/fees.yaml` (30 bps, floor 0.05), held with the money and taken only at release.

Devnet run, 16 Oct 2026, round 1 under the first rules (test units of the app's own test mint; live Qloo answers): a smart water bottle (Lagos) OPEN,
target 150, reserve 45; canned oat-milk cold brew (London) REFUSE, audience too thin.

Also in round 1: a cozy farming video game REFUSE, audience too thin and no demographic signal; the same water-bottle idea with no key:
CANNOT_DECIDE.

The water bottle's 45-unit pre-order: lock `5mCZbS5MLXD9sjQiXXMpQXGWGELwWeadKzmsVzr1So6n5Df4MjH8F7smwJaNPG9H2xDC8MTHTozDzsf73PdE8Qys`; evidence
without the claim id refused (HTTP 422); referee PASS + release
`4HhTwWcC6tMwtYYzaHNmYByPUDadZUuMQpthfwenw5fjr58jBJyrxw7SUUc89NUddzABSebZJT28Y8p3UwwhkzJm`,
`5H7WmpNZDWpeBh1PWWqso65WZjognA7JkXXJCSLmLSceAtgbaGfU1sZTBDmY6ZGhFnpUCBL8aT9k6oSTw7Uoski`; the maker's wallet then held 45 test units. The evidence
page in that run was an echo service showing the claim id (a demo, not a product page).

**Two more Qloo calls, used only where they change the target** (never the verdict):

- **Named buyer group** (`/v2/audiences`, all ten audience types, cached privately): when a word after "for" in the idea names one of
  Qloo's audience segments ("runners" -> Running, "gamers" -> Video Gamer, "vegans" -> Veganism), the segment is looked
  up in the idea's top 20 ranked segments (`/v2/insights` `urn:audience`).

Ranked above 0.55: confirmed, target x 1.2;
  absent or neutral: refuted, target x 0.6, and the report says so. No named segment: no change, no call counted.
- **Recommendations** (`/v2/insights` with `filter.type` = the idea's kind, 10 results): products this taste also
  likes.

Those with affinity >= 0.8 that are not already matched are adjacent demand: >= 5 -> target x 1.2; <= 1 ->
  target x 0.8; else no change. A failed call changes nothing.

## The crossing agent and what Qloo sets (17 Oct 2026)

`POST /api/cross {ref | idea, place?, product?}` starts the server-side agent (`apps/wanted/knos_wanted/agent.py`), and
`GET /api/cross?id=&since=` streams its steps. Each Qloo step carries the call, its input, an output summary and its
effect.

On OPEN the report's `decision.plan` holds what Qloo's evidence SET:

- **who**: the top age and gender (`urn:demographics`) and the informative segments (`urn:audience`);
- **where**: the launch cities (`urn:entity:destination`, explainability on);
- **price tier**: the best premium spending-habit segment (Gourmand Fine Dining, Boutique Hotels, High Fashion, Watch
  Collecting, Art Collectibles, Angel Start Up Investing, Wine Enthusiast, Real Estate) minus Discount Shoppers, each
  absent one counted at Qloo's neutral 0.5. Above +0.05 is premium, below -0.05 is budget, otherwise mid. The unit price
  is 4 / 2 / 1 test units: a scale, not a price recommendation;
- **held money target and reserve**: in units and in test units (units x unit price);
- **unserved audience**: what the idea's side has and the leader's does not.

The tag step is one `/v2/tags` call with `feature.semantic_search=true` on the product phrase.
`feature.explainability=true` is sent on the destination and recommendation calls, and the explanations are kept in
the report.

## Research intake (16 Oct 2026)

`POST /api/research {ref}` -> a research card (`apps/wanted/knos_wanted/research.py`): the proven result quoted from the
abstract with its DOI, OpenAlex `cited_by_count`, year, retraction status, Nobel recognition from
`apps/wanted/knos_wanted/data/nobel.toml` (rows quote and link nobelprize.org press releases), and the product it enables.

After the demand check, "why it never crossed" flags the three walls only with evidence: money before proof (>= 5 years,
Nobel or >= 1,000 citations, and no Qloo product for it), slow judges (an OpenAlex field or topic that is clinical or
regulated), failed attempts (Qloo products like it with popularity < 0.3); otherwise "no evidence".

## Sibyl is the agent's memory; the chain holds the money rules

Sibyl is the agent's working memory. Each crossing is remembered (claim `crossing:<hash of the paper id>`: when, the
product phrase, the decision, the report). The next crossing of the same paper starts from that memory, for example by
reusing the product phrase the maker settled on.

Each decision, lock and release is also written to the Knos Record (`company.record_check`, `record_lock`,
`record_release`).

Memory never moves or blocks money. A double release is refused by the on-chain payment program: before any release the server
reads the order account on devnet (`preorder.chain_gate`).

Once knos_pay has paid or refunded an order, the account is closed, and the server answers HTTP 409 "refused: the order
... is closed on devnet (already released or refunded); knos_pay pays a stage once", with `refused_by: the order
on devnet (read from the chain)`. The program would refuse it too, because the order account no longer exists.

**Pre-orders are reported available only when they work.** At start and every 10 minutes the server builds the
transaction a 5-unit pre-order sends (test-mint top-up and the stage's PANEL order with its three referee keys, through
config/fees.yaml and config/referees.yaml) and runs devnet `simulateTransaction` with the demo buyer (nothing is sent);
`/api/status` `preorders` is `available: false` with the reason otherwise.

An unexpected error reaches the user as
"the server could not finish this step (reference ...)", and the server logs the reference with the error.

## How Knos reaches Qloo (MCP flow, optional)

```
browser --> Knos server (Python) --JSON lines--> apps/wanted/bridge/qloo_bridge.mjs --MCP stdio--> qloo mcp --> Qloo
                                                  (official MCP SDK 1.30.1)          (@qloo/qloo-harness 0.1.26+)
```

- Only Qloo's supported stack: `qloo mcp`, the canonical local MCP server of the public harness, started from the
  backend with the official MCP SDK, as Qloo's starter `starter/mcp-client/backend.mjs` does
  (Qloo's public examples). Not used: hosted MCP endpoints (there are
  none), the integrate/plan/build modes. In this flow `qloo api` is not needed: the nine workflows
  cover every question below (the decision check above uses `qloo api mcp`).
- Why a Node sidecar and not a Python MCP client: it is the SDK and version Qloo's starter pins, the harness
  already needs Node 22.19+, and the Python service stays on the standard library.
- Mode: **live** when `qloo_capabilities` reports `adapter.ready: true` (a credential is configured on the server);
  otherwise **MOCK**: Knos's own MCP server (`knos_wanted.mock_mcp`) with the same ten tool names and the same
  envelope, every answer labelled "MOCK (synthetic, not real Qloo data)". `python -m knos_wanted status` says
  which, and why, without calling Qloo.

## The maker flow

| # | Step | Tool | Request (smallest that answers) |
|---|---|---|---|
| 1 | the idea's taste words become tag URNs | `qloo_find_tags` | `{query, limit: 5}` per word, at most 3 words |
| 2 | existing products that stand for the idea, and its rivals | `qloo_describe` | `{entity, type}`; an ambiguous name returns candidates |
| 3 | **the maker confirms** which tag and which entity each word means | (none) | only offered candidates are accepted; "none of these" and "look up another name" are offered |
| 4 | who | `qloo_audience_demographics`, `qloo_entity_tags` | the confirmed proxy's id; up to 3 proxies for tags |
| 5 | where | `qloo_where_popular` | `{entity: id, within: place, limit: 10}` |
| 6 | rising or not | `qloo_trends` | proxy + rivals (at most 5), the last 12 weeks |
| 7 | vs rivals | `qloo_compare_audiences` | proxies (A) against rivals (B) |
| 8 | fit | `qloo_rank` | variants and rivals as options, the place as `signal_location`, an audience phrase when the idea names one |
| 9 | the report | (Knos) | sections, the lean (Knos's rule, in the app README), the trail, the report's sha256 |

The idea's text never leaves the Knos server: only the planner's search words do.

## The buyer agent flow

1. The buyer names things they like (brands, places, films) and a vibe or two, never who they are.
   `knos_wanted.privacy` refuses e-mails, phone numbers, handles, links, addresses and sentences about a person
   before any call.
2. `qloo_describe` per liked thing and `qloo_find_tags` per vibe; the buyer confirms each match.
3. `qloo_recommend` per target type the buyer picks: what people with this combined taste also like.
4. `qloo_rank` on the products open for pre-order: a product that is not built has no Qloo entity, so Knos ranks the
   existing product its maker confirmed as its proxy, one call per product type (Qloo ranks one option type per call
   and says scores from separate calls are not comparable).
5. Pre-order: the existing Knos graduation pre-order (`knos.graduation.preorder_ix`, a knos_pay FundOrderWallet),
   by the demo buyer (the app's devnet test wallet) or the buyer's own wallet.

Knos keeps no copy of a buyer's tastes: the session lives in the server's memory for 30 minutes and is not recorded.

## The request-to-result trail

Every call adds one row: the step, the tool, the request as sent (no key, no personal data), why it was asked, the
status (`ok`, `empty`, `needs_input`, `partial`, `degraded`, `error`), the result count, retries and whether it came
from the cache. Every confirmation adds a row naming the chosen id.

The page shows the trail under the heading "aggregate taste, not a prediction about one person"; its sha256 goes
into the Knos Record.

## Record, anchor, fees

| Event | Knos Record (Sibyl) | Fee line (config/fees.yaml) |
|---|---|---|
| demand report | WARM claim `demand:<hash>` + COLD `experiment` | none: the report is free until the founder sets a price |
| pre-order locked | COLD `funding` + the claim's new state | `funding` (0 at lock) |
| pool paid to the maker on delivery | (the payout path of Knos) | `payout` (taken by knos_pay at release), `graduation` (decided, collected off chain) |
| anchor | Merkle root of the unanchored lines in one devnet Memo transaction, after each pre-order | none |

Public lines hold hashes, statuses, tool names, addresses and amounts: never the idea text, a buyer's tastes or a
Qloo result.

## Rules kept

- Key only on the server (`QLOO_API_KEY` in the server's environment, or `qloo setup --qloo`): never in the
  browser, the repository, a log or a recording. The bridge forwards the environment to `qloo mcp` and reads no value.
- Bounded retries: only when the envelope says `error.retryable`, at most two more, with backoff.
- Minimal cache: in this flow, live `ok`/`empty` answers only, 15 minutes, at most 200 files, under `.cache/`
  (git-ignored). The decision check's client (`qloo_rest.py`) keeps an answer with no time limit and a refused question 1 day.
  MOCK answers are never cached. No Qloo response is committed; the tests use synthetic bodies only.

## What a report does not establish

- It describes how audiences of EXISTING products behave, not whether this product will sell: no units, revenue,
  price or conversion.
- It depends on the matches the maker confirmed; another proxy gives another report (that is why the maker
  confirms, and why the choices are in the trail and the hash).
- Ranks and affinities are relative within one call; scores from separate calls are not comparable.
- In MOCK mode every number is synthetic and says so.
- A pre-order on devnet is test money: it shows the flow, not willingness to pay.

## Run it

```bash
npm install --global @qloo/qloo-harness && qloo --version           # 0.1.26 or newer
sh apps/wanted/bridge/install.sh                                      # the official MCP SDK beside the bridge
PYTHONPATH=src:apps/wanted python -m knos_wanted status
PYTHONPATH=src:apps/wanted python -m knos_wanted serve
PYTHONPATH=src:apps/wanted python -m pytest -q apps/wanted/tests     # no network, no key
```

With a key: `qloo setup --qloo` (typed once into the hidden prompt), then `qloo setup --status` must say "Qloo data:
ready" before a live demo.
