# Knos: proven research, funded products (apps/wanted/)

**Live:** https://knos.onrender.com/app/. It runs on a free instance that sleeps, so the first visit can take a minute.
Phone or desktop, nothing to install. **License:** MIT ([LICENSE](LICENSE)).

Landmark research often never becomes a product: "the overall failure rate of drugs that passed into phase 1 trials to
final approval is 90%" ([Errington, J Clin Invest 2024](https://www.jci.org/articles/view/177383)). Regulatory T cells were
described in 1995 and earned the 2025 Nobel award in medicine, and "Several of these treatments are now undergoing
clinical trials" (the Nobel Assembly's 2025 press release, [nobelprize.org](https://www.nobelprize.org/)). Knos takes such a result to a product
people pre-order, with the money held by the program and paid to the maker only on proof.

**Directional demand evidence, not a sales forecast.** Every Qloo result describes
aggregate taste, not a prediction about one person.
Target, reserve and price come from published rules over Qloo's numbers, not from a forecast.

## The app

One app at `/app/`, with a step for each person in the crossing.

1. **Researcher.** Paste a DOI, arXiv, PubMed or OpenAlex id. Knos's agent runs the whole crossing on the server and the
   page shows each step live, with the Qloo call, its input, a summary of its output, and how it changed the decision.
   The steps run in this order:
   - read the paper and quote its proven result;
   - name the product the result enables;
   - ask Qloo who, where, at what price, and against which leader;
   - decide OPEN or REFUSE by code, and set the hold target and reserve;
   - say why the result never crossed (money before proof, slow referees, failed attempts), each only with evidence.
2. **Buyer.** A product page targeted by Qloo: who it is for, the launch cities, the price tier and the funding goal.
   There are two ways to pre-order:
   - **A Solana Action (Blink):** `GET/POST /api/actions/preorder`, with rules at `/actions.json`. Any wallet signs, and
     the server never holds the buyer's key.
   - **Your passkey:** sign in with a passkey (no seed phrase). It is a LazorKit smart wallet on devnet; the faucet puts
     devnet test units in it, and your passkey signs the pre-order (secp256r1 precompile). The server relays and pays fees;
     no server key buys for anyone.

   Then come a hold receipt with explorer links and a milestone tracker.
3. **Maker / funder.** Open milestones are listed here. The maker proves one with a public evidence page, code checks
   it, and two of three referee keys release the hold on devnet. A second release of the same order is refused by the
   chain: the order account is closed.

Everything runs on Solana devnet with test units: no real money.

## How Qloo is used (each call sets something)

| Step | Qloo endpoint | What it sets |
|---|---|---|
| closest products, leader | `/search` (+ `/entities`) | the relevance gate and the market leader |
| the idea's tastes | `/v2/tags` with `feature.semantic_search` on the product phrase | taste tags (shown) |
| who | `/v2/insights` `urn:demographics` | WHO: the age and gender to target; checks a named audience |
| audience and price | `/v2/insights` `urn:audience` (top 20) | the audience gate and strength; the PRICE TIER from spending-habit segments (Gourmand Fine Dining, Boutique Hotels, ... vs Discount Shoppers) |
| named buyer group | `/v2/audiences` | confirms (x1.2) or refutes (x0.6) the group named after "for" |
| where | `/v2/insights` `urn:entity:destination` (explainability on), `urn:entity:place`, `urn:heatmap` | WHERE: the launch cities, named places, map hot spots |
| adjacent demand, brand ladder | `/v2/insights` with `filter.type` = the idea's kind (explainability on) | target x1.2 / x0.8 |
| rising or falling | `/v2/trending` | not counted when Qloo's series does not move (it ends 2026-07-24) |
| vs the leader | `/v2/analysis/compare`, or the leader's own segments | the owned and served gates, the reserve, the audience the leader does not serve |

Rules and thresholds: [docs/reference/DEMAND_CHECK.md](../../docs/reference/DEMAND_CHECK.md). Without a Qloo key the
answer is "cannot decide: no Qloo evidence", and pre-orders never open.

Sibyl is the agent's **working memory**. Before a crossing the agent recalls what it learned about the same paper,
such as the product phrase it settled on and the last decision. After the crossing it remembers this one. Memory never
moves or blocks money; the hold rules live in knos_pay on chain.

## For other agents: MCP over HTTP

`POST /mcp` speaks JSON-RPC (Streamable HTTP; `initialize`, `tools/list`, `tools/call`), and callers need no key. Its
tools are `knos_cross` (paper id -> every step and the decision), `knos_research_card` and `knos_demand_check`. This is
an optional door; the product is the web page.

## Run it

```sh
# from the root of the Knos checkout (Python 3.12)
pip install . "./apps/wanted[hold,auth,config]"
export QLOO_API_KEY=... QLOO_BASE_URL=...   # the key and the API host Qloo gave you
PYTHONPATH=apps/wanted python -m knos_wanted serve        # http://127.0.0.1:8080
```

Docker: `docker build -f apps/wanted/Dockerfile -t knos .` (python:3.12-slim). `render.yaml` deploys it on Render.

| Variable | What |
|---|---|
| `QLOO_API_KEY`, `QLOO_BASE_URL`, `QLOO_MONTHLY_BUDGET` | Qloo, server side only (4 calls/s, monthly cap; the cache rule is under "Qloo data and personal data") |
| `KNOS_WANTED_DEVNET_KEYPAIR`, `KNOS_WANTED_REFEREE_KEYS`, `KNOS_WANTED_MAKER_WALLET`, `KNOS_WANTED_MINT` | devnet hold: relayer (fees, rents) and test-mint authority (the faucet), 3 referee keys (one server: not an independent panel), payee, test mint |
| `GOOGLE_CLIENT_ID` | Google sign-in (shown only when set) |
| `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `ORCID_BASE` | ORCID sign-in (OAuth code flow; `ORCID_BASE=https://sandbox.orcid.org` for the sandbox) |
| `RESEND_API_KEY`, `KNOS_WANTED_EMAIL_FROM` | email magic links; without them, an email is only a display label |
| `KNOS_WANTED_SESSION_SECRET`, `KNOS_WANTED_RP_ID` | sessions and passkeys (RP id = the site's host) |

## Updates since 30 Sep 2026

- The researcher view and the server-side agent: a paper id becomes a live crossing, and every step names its Qloo call.
- Qloo's evidence now sets who, where (launch cities), the price tier, and the hold target and reserve. The calibrated
  gates are relevance, clone, owned/served and contradiction. Explainability is on wherever Qloo returns it.
- Landmark research intake (OpenAlex, Crossref, PubMed, arXiv), with sourced Nobel and "no product yet" rows.
- Pre-orders: a Solana Action (Blink) for any wallet; a passkey-signed pre-order (LazorKit smart wallet); a devnet
  preflight in `/api/status`; the 1,232-byte transaction limit checked; milestones released by a 2-of-3 panel; a double
  release refused by the chain.
- MCP over HTTP.
- Fixes: the legacy pre-order routes under `/api/preorder/` (faucet, tx, submit and the sample route) need a signed-in session; PyYAML is pinned in the
  image; Python 3.12; no raw errors are shown to users.
- Six roles on one phone page in seven languages (ar is RTL); the official qloo-harness MCP server runs LIVE on
  the server (its ten tools answer at /mcp as `qloo_*`; REST carries the decision, labelled); launch cities scoped to
  the market; taste persona, brand ladder, venue price levels, audience signals, explainability shown at their steps;
  x402 pays for a report per use on devnet; receipts show measured finality and the verifier; the record root anchors
  on devnet; Sibyl is the agents shared working memory (plan, reference shelf, conflict refusal, FTS search).

## The older confirm-each-match flow (MCP sidecar, optional)


```bash
# once: Qloo's harness (Node 22.19+) and the official MCP SDK beside the bridge
npm install --global @qloo/qloo-harness          # qloo --version must be 0.1.26 or newer
sh apps/wanted/bridge/install.sh                 # @modelcontextprotocol/sdk 1.30.1, as Qloo's starter pins it

# from the root of the Knos checkout
PYTHONPATH=src:apps/wanted python -m knos_wanted status                     # live or MOCK, and why (no Qloo call)
PYTHONPATH=src:apps/wanted python -m knos_wanted serve                      # http://127.0.0.1:8080, no login
PYTHONPATH=src:apps/wanted python -m knos_wanted maker "A late-night oat-milk coffee bar for students in London" \
    --rival Starbucks --rival Pret --pick first                             # the maker flow in a terminal
```

**Without a Qloo key the build refuses to decide.** `POST /api/check` answers CANNOT_DECIDE ("cannot decide: no Qloo
evidence") with zero Qloo calls, `/api/status` says `qloo_rest.rest: false` and `no_key_behaviour`, the page badge
says "Qloo: off", and pre-orders never open. With the key set, `/api/status` reports `mode: live` (the REST path).
Only the older terminal/MCP flow below (`maker`, `buyer`) still falls back to Knos's MCP server,
**MOCK (synthetic, not real Qloo data)**,
when the harness has no credential; every answer of that flow is labelled so, and none of it can
open pre-orders.

## What is Qloo-powered

Qloo is reached only from the server, only through Qloo's canonical local MCP server `qloo mcp`
(@qloo/qloo-harness), started by `bridge/qloo_bridge.mjs` with the official MCP SDK exactly as Qloo's starter
`starter/mcp-client/backend.mjs` does. Nine workflows, each where it answers a question of the product:

| Step | Tool | Why |
|---|---|---|
| Maker: the idea's taste words | `qloo_find_tags` | turn "oat-milk", "late-night" into tag URNs the maker picks from |
| Maker: what stands for the idea, and its rivals | `qloo_describe` | resolve existing products to one Qloo entity each; ambiguous names come back as candidates the maker confirms |
| Who | `qloo_audience_demographics`, `qloo_entity_tags` | aggregate age and gender affinity of the proxy's audience; the concepts that characterise it (and whether the maker's chosen taste is among them) |
| Where | `qloo_where_popular` | heatmap cells around the maker's place |
| Rising or not | `qloo_trends` | population percentile over 12 weeks for the proxy and the rivals |
| Vs rivals | `qloo_compare_audiences` | the proxy's audience against the rivals' |
| Fit | `qloo_rank` | which variant of the idea or rival fits this place and audience best |
| Buyer: what this taste also likes | `qloo_recommend` | per target type the buyer picks, from the buyer's confirmed signals |
| Buyer: which unbuilt product fits | `qloo_rank` | the confirmed proxies of the products open for pre-order, against the buyer's signals |

In this flow `qloo api` is not used: the workflows cover every question (the decision check asks `qloo api mcp`
first). Not Qloo-powered: the planner that proposes search words
(keyword rules by default, or any OpenAI-compatible LLM you configure; it proposes words only, never numbers), the
one-word lean, the page, the Knos Record and the pre-order hold (Knos).

## How the lean is decided (Knos's rule, not Qloo's)

- **Fit:** +1 if a variant of the idea ranks above every rival in `qloo_rank` for the place and audience, else -1.
- **Trend:** +1 if the proxy's population percentile rose by 2 points or more over 12 weeks, -1 if it fell by 2 or more.
- **Audience:** +1 if one age segment leans in with a demographic affinity above 0.1.

Two or more points: "leans wanted". 0 or 1: "mixed". Below 0: "weak". Fewer than two of these sections with data:
"insufficient evidence". The thresholds are choices of Knos, stated here so anyone can disagree with them.

## Record and money

- Every demand report: a WARM claim `demand:<report hash>` and a COLD `experiment` event in the Knos Record
  (`knos.record`, Sibyl). Every pre-order: a COLD `funding` event and the claim's new state. After each pre-order
  the unanchored lines are anchored on Solana devnet (`knos.record.anchor`, signed by the app's devnet test wallet);
  `python -m knos_wanted anchor` does it on demand. The record holds hashes, statuses, tool names, addresses and
  amounts: never the idea text (only its sha256), never a buyer's tastes, never a Qloo result.
- Pre-orders use Knos's graduation pre-order pool (`knos.graduation.preorder_ix`, knos_pay FundOrderWallet): money
  is paid to the maker only on delivery through Knos's referee, and refunded after the deadline (14 days) otherwise.
- Fees come from `config/fees.yaml` (`knos.money.fees_config`): `funding` 0 at lock, `payout` taken by knos_pay at
  release, `graduation` decided and collected off chain. The demand report has no fee line: it is free until the
  founder sets one. Devnet only, test units of a mint this app creates, no real money.

## Qloo data and personal data

- The key lives only in the server's environment (`QLOO_API_KEY`) or the harness's private config (`qloo setup
  --qloo`). It never reaches the browser, the repository, a log or a recording.
- No personal data goes to Qloo: `knos_wanted.privacy` refuses e-mails, phone numbers, handles, links, addresses
  and sentences about a person before any call. Buyers name things they like, never who they are.
- Smallest requests (limits of 3 to 12), bounded retries (only when Qloo says `retryable`, at most 2 more, with
  backoff), and a private cache on the server only. The demand check (`/api/check`, the REST client) keeps a live
  answer with no time limit and a refused question for 1 day. The older MCP flow keeps live answers for 15 minutes, at
  most 200 files under `.cache/` (git-ignored). MOCK answers are never cached. No Qloo response is ever committed; the tests use synthetic bodies only.

## Deploy (one service)

```bash
# from the root of the Knos checkout: the image installs Knos, this app, Node, the harness and the MCP SDK
docker build -f apps/wanted/Dockerfile -t knos-demand .
docker run -p 8080:8080 --env-file apps/wanted/.env knos-demand
```

| Variable | Needed for | Without it |
|---|---|---|
| `QLOO_API_KEY` (+ `QLOO_BASE_URL`, the API host Qloo gave you; `QLOO_TRUSTED_BASE_URL` defaults to it) | live Qloo data | the check answers CANNOT_DECIDE (no Qloo evidence); the MCP flow runs MOCK (synthetic), labelled |
| `KNOS_WANTED_DEVNET_KEYPAIR` | pre-orders and anchoring (a devnet test wallet with a little devnet SOL; path or JSON byte array) | hold buttons explain what is missing |
| `KNOS_WANTED_MINT` | the same test mint across restarts | a test mint is created on first use |
| `KNOS_WANTED_RECORD` | where the Knos Record lives | `~/.knos/record` |
| `KNOS_WANTED_LLM_BASE_URL`, `_API_KEY`, `_MODEL` | LLM planner (OpenAI-compatible) | keyword planner |
| `KNOS_RPC` | a devnet RPC of your choice | `https://api.devnet.solana.com` |

## Tests

```bash
# from the root of the Knos checkout; no network, no key: Knos's MOCK server is the fake MCP server
PYTHONPATH=src:apps/wanted python -m pytest -q apps/wanted/tests
```

`tests/test_bridge.py` drives the real Node bridge and SDK against the MOCK server as a separate process; it is
skipped, with the reason, where Node or the SDK is not installed. Knos's own suite runs these too
(`tests/test_fold_wanted.py`).

## License

MIT, see [LICENSE](LICENSE). Knos is MIT licensed. Qloo data is Qloo's and is used under its API terms.
