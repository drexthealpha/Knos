# Knos: proven research, funded products (apps/wanted/)

The demand check of Knos: see whether people want a research product, from free public signals. The same Knos proves
research claims with agents on NEAR testnet ([the front door](https://drexthealpha.github.io/Knos/)).

The goal: Knos turns any research into a product billions of people use, in days, not years. No customers yet.

**Live:** https://knos.onrender.com/app/. It runs on a free instance that sleeps, so the first visit can take a minute.
Phone or desktop, nothing to install. **License:** MIT ([LICENSE](LICENSE)).

Landmark research often never becomes a product: "the overall failure rate of drugs that passed into phase 1 trials to
final approval is 90%" ([Errington, J Clin Invest 2024](https://www.jci.org/articles/view/177383)). Regulatory T cells were
described in 1995 and earned the 2025 Nobel award in medicine, and "Several of these treatments are now undergoing
clinical trials" (the Nobel Assembly's 2025 press release, [nobelprize.org](https://www.nobelprize.org/prizes/medicine/2025/press-release/)). Knos takes such a result to a product
people pre-order, with the test money held by the program and released to the maker when the milestone check passes.

**Directional demand evidence, not a sales forecast.**

## The app

One app at `/app/`, with a step for each person in the crossing.

1. **Researcher.** Paste a DOI, arXiv, PubMed or OpenAlex id. Knos's agent runs the whole crossing on the server and the
   page shows each step live, with its source, its input and its output:
   - read the paper and quote its proven result;
   - name the product the result enables;
   - read the open signals for that product and decide by code;
   - say why the result never crossed, each wall only with evidence.
2. **Buyer.** A product page and a pre-order. A Solana Action (Blink) at `GET/POST /api/actions/preorder` (rules at
   `/actions.json`) lets any wallet sign; a passkey (a LazorKit smart wallet on devnet) signs too, and the server relays
   and pays fees. No server key buys for anyone. Pre-orders open only on a report with a pre-order target.
3. **Maker / funder.** Open milestones are listed here. The maker proves one with a public evidence page, code checks
   it, and two of three referee keys release the hold on devnet. A second release of the same order is refused by the
   chain: the order account is closed.

Everything here runs on Solana devnet with test units: no real money.

## How the demand check decides

`knos_wanted.check` asks free, keyless public sources about the idea's subject (`knos_wanted.open_signals`), each
row with its link:

| Source | Counts when |
|---|---|
| Wikipedia (Wikimedia pageviews) | the subject's article has at least 100 views a day over the last 60 days |
| News (GDELT) | at least 50 articles in 3 months |
| Hacker News | at least 5 stories in 2 years |
| Research papers (OpenAlex) | at least 200 works since 2023 |
| Money down | any pre-order already locked on this server for the idea |

OPEN when 2 of them count, REFUSE when the subject was found and fewer count, CANNOT_DECIDE when no source answered.
No language model decides. None of these sources says who buys or in which city, so the report names no audience and
no launch city, and sets no pre-order target. Off the hosted app no source is asked unless `KNOS_OPEN_SIGNALS=on`.

The Knos record's memory store is the agent's **working memory**. Before a crossing the agent recalls what it learned about the same paper,
such as the product phrase it settled on and the last decision. After the crossing it remembers this one. Memory never
moves or blocks money; the hold rules live in knos_pay on chain.

## For other agents: MCP over HTTP

`POST /mcp` speaks JSON-RPC (Streamable HTTP; `initialize`, `tools/list`, `tools/call`), and callers need no key. Its
tools start with `knos_cross` (paper id -> every step and the decision) and `knos_demand_check`; `tools/list` gives the
full set, including the NEAR job tools and `knos_check_proof`. This is an optional door; the product is the web page.

## Run it

```sh
# from the root of the Knos checkout (Python 3.12)
pip install . "./apps/wanted[hold,auth,config]"
PYTHONPATH=apps/wanted python -m knos_wanted serve        # http://127.0.0.1:8080
PYTHONPATH=src:apps/wanted python -m knos_wanted check "a solar powered music festival"   # one check in a terminal
```

Docker: `docker build -f apps/wanted/Dockerfile -t knos .` (python:3.12-slim). `render.yaml` deploys it on Render.

| Variable | What |
|---|---|
| `KNOS_OPEN_SIGNALS` | `on` asks the open sources off the hosted app; `off` stops them on it |
| `KNOS_WANTED_DEVNET_KEYPAIR`, `KNOS_WANTED_REFEREE_KEYS`, `KNOS_WANTED_MAKER_WALLET`, `KNOS_WANTED_MINT` | devnet hold: relayer (fees, rents) and test-mint authority (the faucet), legacy 3 referee keys on one server, used only when `KNOS_REFEREE_FROST_SHARE` is unset, payee, test mint |
| `KNOS_REFEREE_FROST_SHARE` | this host's share of the FROST 2-of-3 referee group across three hosts (`knos_wanted.referee`) |
| `GOOGLE_CLIENT_ID` | Google sign-in (shown only when set) |
| `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET`, `ORCID_BASE` | ORCID sign-in (OAuth code flow; `ORCID_BASE=https://sandbox.orcid.org` for the sandbox) |
| `RESEND_API_KEY`, `KNOS_WANTED_EMAIL_FROM` | email magic links; without them, an email is only a display label |
| `KNOS_WANTED_SESSION_SECRET`, `KNOS_WANTED_RP_ID` | sessions and passkeys (RP id = the site's host) |
| `KNOS_WANTED_RECORD` | where the Knos Record lives (default `~/.knos/record`) |
| `KNOS_RPC` | a devnet RPC of your choice (default `https://api.devnet.solana.com`) |

## Record and money

- Every demand report: a WARM claim `demand:<report hash>` and a COLD `experiment` event in the Knos Record
  (`knos.record`). Every pre-order: a COLD `funding` event and the claim's new state. After each pre-order
  the unanchored lines are anchored on Solana devnet (`knos.record.anchor`, signed by the app's devnet test wallet);
  `python -m knos_wanted anchor` does it on demand. The record holds hashes, statuses, source names, addresses and
  amounts: never the idea text (only its sha256), never a buyer's tastes.
- Pre-orders use Knos's graduation pre-order pool (`knos.graduation.preorder_ix`, knos_pay FundOrderWallet): money
  is paid to the maker only on delivery through Knos's referee, and refunded after the deadline otherwise.
- Fees come from `config/fees.yaml` (`knos.money.fees_config`): `funding` 0 at lock, `payout` taken by knos_pay at
  release, `graduation` decided and collected off chain. Devnet only, test units of a mint this app creates, no real money.

## Personal data

No personal data leaves the server: `knos_wanted.privacy` refuses e-mails, phone numbers, handles, links, addresses
and sentences about a person before any source is asked.

## Tests

```bash
# from the root of the Knos checkout; no network, no key
PYTHONPATH=src:apps/wanted python -m pytest -q apps/wanted/tests
```

Knos's own suite runs these too (`tests/test_fold_wanted.py`). The Record tests need `sibyl-memory-client` (below 0.9);
without it `tests/test_research_record.py` skips and a few Record tests fail.

## License

MIT, see [LICENSE](LICENSE). Knos is MIT licensed.
