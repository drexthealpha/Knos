# Qloo: what the demand check uses, and where each detail comes from

Read 14 Oct 2026. Nothing here is Qloo response data.

## The supported stack (the only one used)

| What | Source |
|---|---|
| Supported surfaces `qloo explore`, `qloo exec`, `qloo api`, `qloo mcp`; minimum harness 0.1.26; excluded: integrate/plan/build modes, hosted MCP endpoints, legacy `qloo api mcp` | [Qloo's starter kit](https://github.com/qloo) `README.md` and `manifest.json` (commit 0db91b8d, 23 Sep 2026) |
| `qloo mcp` is a local stdio server with no hosted URL; start it from a backend with the official MCP SDK and `env: process.env` so `QLOO_API_KEY` reaches it; the chain find_tags/describe -> confirm -> recommend/rank/where_popular; six statuses ok/empty/needs_input/partial/degraded/error; retry only when `error.retryable` | kit `starter/mcp-client/README.md` and `backend.mjs`; SDK pin `@modelcontextprotocol/sdk` 1.30.1 in `starter/mcp-client/package.json` |
| Key only on the server, never in a repository, browser bundle, public MCP config or recording; smallest request; cache only what is needed; bounded retries; no bulk scraping | kit `docs/API_ACCESS.md` |
| No personal data to Qloo (names, e-mails, device ids, account ids, location histories); results are aggregate affinities, not evidence about a person; ask for clarification when an entity or tag choice changes the result | kit `docs/SAFE_USE.md` |
| `QLOO_BASE_URL` and `QLOO_TRUSTED_BASE_URL` set to the same URL to trust a gateway for one invocation; `qloo setup --status --json`; `qloo mcp` advertises `qloo_capabilities` plus nine workflows and with no credential fails calls with `QLOO_AUTH` | `@qloo/qloo-harness` 0.1.26 `README.md` (npm package, installed 14 Oct 2026) |

## The tools, as `qloo mcp` lists them (harness 0.1.26, `tools/list` without a key, 14 Oct 2026)

`qloo_capabilities`, `qloo_recommend`, `qloo_rank`, `qloo_describe`, `qloo_where_popular`, `qloo_compare_audiences`,
`qloo_entity_tags`, `qloo_audience_demographics`, `qloo_trends`, `qloo_find_tags`. Inputs the demand check relies on:

| Tool | Inputs used | Notes from the schema / the harness's builders (dist/qloo-tools.js) |
|---|---|---|
| `qloo_find_tags` | `query`, `limit` (1-20) | `GET /v2/tags`, `feature.semantic_search` true by default; results `{id, name, type, popularity, affinity}` |
| `qloo_describe` | `entity`, `type` | names are resolved; an ambiguous name returns `needs_input` with `resolution.issues[].candidates[] {id, name, type, rank, ...}`; an id resolves as `match: identifier` |
| `qloo_audience_demographics` | `entity`, `entity_type`, `limit` | `filter.type=urn:demographics`; results `results.demographics[]` as Qloo returns them |
| `qloo_entity_tags` | `entities` (1-10), `entity_type`, `limit` | `filter.type=urn:tag` |
| `qloo_where_popular` | `entity`, `entity_type`, `within`, `limit` | `filter.type=urn:heatmap` + `filter.location.query`; cells sorted by `query.affinity` |
| `qloo_trends` | `entities` (1-5), `entity_type`, `start_date`, `end_date`, `limit` | one `GET /v2/trending` per entity; result `series[] {entity, points[]}` |
| `qloo_compare_audiences` | `group_a`, `group_b`, `target_type`, `limit` | `GET /v2/analysis/compare` |
| `qloo_rank` | `options` (1-10), `option_type`, `signals` or `signal_location` (+ `demographic`) | `filter.results.entities` = options; a demographic needs `signal_location`; "scores from separate calls are not comparable" |
| `qloo_recommend` | `target_type`, `signals`, `signal_tags`, `limit`, `explain` | `feature.explainability=true` by default |

Entity types: Insights types `artist, book, brand, movie, person, place, podcast, tv_show, videogame`; search types add
`locality, actor, album, author, director`.

## Where a detail is not documented, and what Knos does

- The exact `results` layout of `qloo_audience_demographics` and `qloo_compare_audiences` is passed through from
  Qloo (`boundedValue(response.results)`). Knos reads `query.age.*` / `query.gender.*` for demographics (Qloo's
  Demographic Insights page) and entity names for compare, and claims nothing more.
- Envelope `schema_version` is `1.0-preview.1`: a preview contract. Knos reads only documented fields and
  degrades a section (it says "error", "empty" or "needs input") rather than guess.
