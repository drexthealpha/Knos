# Idea in, then wanted? (steps 1 and 2 of the one flow)

Research dies in the valley of death on three walls: money comes before proof, referees are slow, and single attempts
fail. Schmidhuber's machine economy, growing toward Kardashev II ([arXiv 2212.11279](https://arxiv.org/abs/2212.11279),
Sec 20), needs a layer that says which research is real and pays for it. Knos is that layer. Every crossing starts
with two steps, in every field of science:

1. **Idea in.** An idea from anyone: a person, a game player, an AI agent, or a claim found in a research source.
   It becomes one Claim record that every later step reads.
2. **Wanted? (wall 1).** Demand evidence, then buyers' money locked before the proof exists, released stage by
   stage as the proof arrives, and refunded where a milestone is missed.

Code: `src/knos/ideas/` (`knos idea ...` on the command line; six read-only `knos mcp` tools, listed when the operator sets `KNOS_MCP_TOOLS=ideas`, so the default tool list is unchanged).

## Step 1: idea in

```
knos idea get pmid:42806035 --out idea.json        # a claim from a research source (live read)
knos idea search clinicaltrials "psilocybin alcohol"
knos idea in "A perovskite cell keeps 95% efficiency after 1000 h damp heat." --by orcid:0000-0002-1825-0097
knos idea in "A faster sort for nearly sorted arrays." --kind agent --agent "Claude"
knos idea who orcid:0000-0002-1825-0097
knos idea sources                                  # live or fixture now, and the key that changes it
knos idea fields                                   # the 26 fields
```

### The Claim record

| field | what it holds |
|---|---|
| `id` | `knos-idea:` and 32 hex of sha256 of the first source id (the DOI when there is one): one paper read twice is one idea |
| `field` | one of the 26 fields of OpenAlex's topic taxonomy (all of science); from OpenAlex when the work has a DOI, else from the arXiv category, the bioRxiv subject, the patent's CPC class or the words |
| `statement` | the claim in one sentence; for a paper its title (Knos never rewrites a paper's words) |
| `origin` | person, player, agent or literature, and who: an ORCID iD or a GitHub account |
| `ids` | DOI, PMID, PMCID, NCT, arXiv, bioRxiv/medRxiv, OpenAlex, patent: those known |
| `sources` | every read that built the record: source, id, URL, `live` or `fixture`, when |
| `retraction` / `risk` | Crossref's Retraction Watch notices for the DOI; a retraction, correction or expression of concern, or a withdrawn or terminated trial, is a **risk signal** shown to the referee and to buyers, never a silent drop |
| `label` | `LIVE ...`, `FIXTURE ...` or `STATED ...` in words |
| `hash` | sha256 of the record without read times: what a pull commitment's terms name |

### Sources, their official APIs, and their rules (read 14 Oct 2026)

| source | API | key | rules Knos keeps |
|---|---|---|---|
| OpenAlex | `api.openalex.org/works` | `OPENALEX_API_KEY`, optional | no key: 10 requests/s and a shared daily budget per IP (a single work is free, a search costs budget); a free key raises both; data CC0 ([help.openalex.org/api/authentication](https://help.openalex.org/api/authentication/)) |
| arXiv | `export.arxiv.org/api/query` | none | one request every 3 s, one connection; metadata CC0 ([arXiv API terms](https://info.arxiv.org/help/api/tou.html)) |
| PubMed | NCBI E-utilities `esummary`/`esearch` | `NCBI_API_KEY`, optional | 3 requests/s without a key, 10 with; `tool` and `email` sent; NCBI's disclaimer is carried on the record ([NBK25497](https://www.ncbi.nlm.nih.gov/books/NBK25497/)) |
| Europe PMC | `ebi.ac.uk/europepmc/webservices/rest/search` | none | open; no published figure, Knos keeps 5 requests/s |
| bioRxiv / medRxiv | `api.biorxiv.org/details`, `/pubs` | none | open; `pubs` links a preprint to its journal DOI (a milestone oracle); no keyword search, so search reads the last 7 days |
| Crossref + Retraction Watch | `api.crossref.org/works/{doi}` (`updated-by`, source `retraction-watch`) | none | public pool 5 requests/s and 1 at a time; polite pool (`mailto`, set `KNOS_CONTACT_EMAIL`) 10/s and 3 ([access and authentication](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)) |
| ClinicalTrials.gov | `clinicaltrials.gov/api/v2/studies` | none | no rate figure in the [OpenAPI spec](https://clinicaltrials.gov/api/oas/v2); Knos keeps 5 requests/s and backs off on 429 |
| Patents | USPTO Open Data Portal `api.uspto.gov/api/v1/patent/applications` (`X-API-KEY`) | `USPTO_ODP_API_KEY`, **required** | free key from [data.uspto.gov](https://data.uspto.gov/apis/getting-started) with a USPTO.gov account; no parallel calls per key. PatentsView moved into the ODP on 20 Mar 2026 ([USPTO bulletin](https://www.uspto.gov/subscription-center/2026/patentsview-migrating-uspto-open-data-portal-march-20)). EPO OPS needs a registration and Lens a token, so neither is used |
| ORCID (identity) | `pub.orcid.org/v3.0/{id}/person`, anonymous | none | 12 requests/s, burst 40, 25,000 reads a day per IP ([ORCID API limits](https://info.orcid.org/faq/what-are-the-api-limits/)) |
| GitHub (identity) | `api.github.com/users/{login}` | none | 60 requests/hour without a token |

Each answer comes from the live API when it is free and allowed. Patents are the only keyed source: without
`USPTO_ODP_API_KEY` a patent read returns a **synthetic** fixture shaped from the ODP response structure, labelled
FIXTURE on the record. `KNOS_IDEAS_FIXTURES=FILE` makes every read offline (the tests use
`tests/fixtures/ideas/recorded-fixture.json`: responses recorded on 14 Oct 2026, abstracts removed).

**Identity.** Reading a public ORCID record shows the iD exists; it does not show the person in front of Knos owns
it. Ownership is "sign in with ORCID"; that token, and paying an ORCID-authenticated payee, belong to knos_pay's
issuer-agnostic release path. A GitHub account is read the same way.

## Step 2: wanted?

```
knos idea wanted idea.json --units 10 --price 4      # demand check + the pull-commitment plan (sends nothing)
knos idea check idea.json trial_registered           # is a stage's milestone met now? evidence + sha256
knos idea commit idea.json --units 10 --price 4 --payee orcid:<iD>@<wallet> \
     --panel 2:<referee1>,<referee2>,<referee3> --program <knos_pay 0.3.34> --wallet buyer.json --mint <test mint>
                                                     # lock the stages; writes idea.commit.json
knos idea sign idea.commit.json stage1 --referee my-referee-key.json          # each referee, where its key is
knos idea sign idea.commit.json stage2 --referee my-referee-key.json --pass --review report.pdf   # review stages
knos idea release idea.commit.json stage1 --sig a.json --sig b.json --wallet relayer.json   # M PASS verdicts: paid
knos idea refund idea.commit.json stage3 --sig c.json --sig d.json --wallet relayer.json    # M FAIL verdicts: refunded now
knos idea refund idea.commit.json stage3 --wallet relayer.json                              # or after its deadline
knos idea state idea.commit.json                     # what the chain holds per stage (nothing to repeat)
knos idea preorder idea.json 5 --wallet buyer.json --mint <test mint>
```

**Demand evidence.** The demand check of [DEMAND_CHECK.md](DEMAND_CHECK.md) runs on the product the idea would become,
through Qloo's official MCP harness. Without `QLOO_API_KEY` it runs Knos's MOCK server, and the result says MOCK.
Directional demand evidence, not a sales forecast.

**Pull commitments, released in stages.** A buyer commits to buy N units at price P if the result is verified (the
advance market commitment pattern). The N x P is locked as one private knos_pay order per **stage**, stage k being
milestone k of the claim in `knos.graduation`'s scope.

`knos.ideas.release_schedule` splits N x P into whole units
that sum exactly to it. The payout fee of `config/fees.yaml` goes on top of each order. Each stage is released when its
milestone oracle is met and the referee signs, and refunded to the buyer after its deadline otherwise (anyone may send
`RefundOrder`):

| oracle | met when (read live) |
|---|---|
| `preprint_posted` | arXiv, bioRxiv or medRxiv lists the claim's preprint |
| `journal_published` | bioRxiv/medRxiv `pubs` names a journal DOI, or the DOI resolves at Crossref, not retracted |
| `trial_registered` | ClinicalTrials.gov has the study and it is not withdrawn |
| `results_posted` | ClinicalTrials.gov `hasResults` is true |
| `not_retracted` | Retraction Watch shows no retraction for the DOI |
| `referee_pass` | a Knos referee verdict for this claim passed (sealed tests, independent re-runs) |
| `lab_qc` | a Knos lab adapter verdict for this claim passed protocol and QC |

**Default stages.** A trial: `trial_registered`, `results_posted`, `referee_pass`. A preprint (arXiv, bioRxiv,
medRxiv): `preprint_posted`, `referee_pass`, `lab_qc`. A paper already published in a journal (a DOI and no preprint
id): `not_retracted`, `referee_pass`, `lab_qc`, so its first stage can be completed (a published paper never becomes
"preprint posted"). `--stages oracle:bps,...` names others.

**Retracted papers.** When Retraction Watch (via Crossref) has a retraction notice for the claim's DOI, `wanted` says
so in a WARNING and the demand reading becomes "retracted: do not fund", whatever the taste data says. `commit`
refuses to lock on it unless the buyer passes `--allow-retracted`.

**The payee is chosen at commit.** `--payee` is required and nothing is assumed: `github:<id>@<wallet>`,
`orcid:<iD>@<wallet>` or a wallet address. It is written into the commitment file, and a verdict that names any other
payee is refused by `release` before anything is sent (the program would refuse it too: the verdict digest binds the
payees).

**The panel.** `--panel M:k1,k2,k3` pins the referee keys on chain. Refused: the funder's or the payee's own key in it,
and keys outside Knos's published referee registry (`config/referees.yaml`) unless the buyer passes `--unlisted-panel`,
in which case the commitment and every output say UNLISTED PANEL. Referees sign with `knos idea sign` where their keys
are; the buyer never holds them.

**`referee_pass` and `lab_qc` need M signed verdicts.** The referee runs `knos idea sign ... --pass|--fail --review
FILE`: the evidence is the report's sha256 and the result. `knos idea check ... --verdict FILE` accepts a referee or lab
verdict only when M referees of the commitment's panel signed it.

An unsigned `{"passed": true}` file is shown as NOT
ACCEPTED, and no verdict can be signed or released on it.

**Pre-orders** go in the claim's pre-order pool (scope 0), paid to the makers when the product is delivered.

**Who releases a stage.** knos_pay pays an order on proof its referee accepts. Two referees work for a stage:

- **A referee panel (knos_pay 0.3.34).** The buyer locks the stage as a PANEL order pinning m of n referee keys
  (`wanted.fund_panel_ix`). Each referee reads the stage's oracle (`wanted.check`) and signs the verdict over its
  evidence hash: "stage met" with the payees (`wanted.sign_stage`), or "stage missed" for an oracle that is not met.
  The relayer sends one signature per transaction (`wanted.stage_verdict_ixs`); at the m-th the program pays the stage
  to the payees, or refunds a missed stage to the buyer at once. A pending oracle gives no verdict to sign. Tested in
  the Solana runtime in `tests/test_ideas_panel.py`, and run on devnet (below).
- **GitHub.** The referee repository's pinned `prove.yml`, signed by GitHub: `wanted.release_audience` gives the
  audience with the evidence hash. The staged path with this referee runs in `tests/test_ideas_litesvm.py` (test issuer).

## On devnet: three ideas, three fields (14 Oct 2026)

`python -m knos.ideas.devnet --wallets DIR --out FILE`: real API reads, real transactions on the public knos_pay
program, in the sample's own **test** mint `GnQv5a8QAmWMhAcKreMkJaS2p9j2LZzrRdsNsdjQq22z` (6 decimals, no freeze
authority; test money, 0 revenue). Buyer `Hm36fQuLeD1vQAL4W8HiMTkCw5nhvohDQC9ycBRpzPsE`, payer
`GFN1cHD9Yvde5B9pbhLbUriD32MupJL5LPd5PkhCqnk7`. Each idea: a pull commitment of 10 units at 4 test units, three stages
locked, one 5-unit pre-order. Demand check: MOCK.

| idea | field | source | stages locked (oracle, test units) | stage 1 now |
|---|---|---|---|---|
| A: a dual A-to-Y and G-to-Y base editor (PMID 42806035) | Biochemistry, Genetics and Molecular Biology | PubMed | not_retracted 8 ([tx](https://explorer.solana.com/tx/5Wvg86L3UW9KJpp4JTbA5jpNgQeUaLbJWfqroAyiHYVyHKf6vDbXp5CN2DaYdj6cZ3jwHKRa62LYEfTtQHwAwBVD?cluster=devnet)), referee_pass 20 ([tx](https://explorer.solana.com/tx/sNh8ygwsEVZsawP1rVR8H1onYEAxWoJsbRj3MZSpAoKDX9qGvR1paF94VquMfifqbfs18iAkobnQFFHbAUzL4qM?cluster=devnet)), lab_qc 12 ([tx](https://explorer.solana.com/tx/2RJPtKmVSqNDZq7rVsFAbcWRk1uWEpA1qLeLm64xXNgrBW3oXuuDfaYA7ck4dsg4JnqCPZz5co5pJ1s8wZk3HzC6?cluster=devnet)) | met (no retraction) |
| B: halide perovskite solar cells (arXiv 1606.00335) | Materials Science | arXiv | preprint_posted 8 ([tx](https://explorer.solana.com/tx/2DHaUNct6kFSfoSeR35cjWApRSeqSX1YtB8iDZHVA6rsbuFNiTusPAhSRFp6xqfv5bLzHUjUp1TdPxYGZgccp2D1?cluster=devnet)), journal_published 12 ([tx](https://explorer.solana.com/tx/4YcX4XQqTjk9XbMtCw3zj2ExWgGKUjd5eJWGP1FXZzhT6gJVDjaHQrSmgFGGpUbEc2AvLV2r37X6x8SqNh7PL31i?cluster=devnet)), referee_pass 20 ([tx](https://explorer.solana.com/tx/5h3gXxQY6nLQVdeC25q2HWPMqmmpSqzowci5SSRtz2J3PcLUXjaorhw6KxysDYuF1SqQJmi1cDeZKKDF5oSNLGxG?cluster=devnet)) | met (arXiv lists it) |
| C: psilocybin for alcohol use disorder (NCT04718792) | Medicine | ClinicalTrials.gov | trial_registered 8 ([tx](https://explorer.solana.com/tx/sZbC2FST97wQZHyvAATieb3x3hCX7Gg6DuPdCJUh5XX7JK1mxNq7fZnnr66PBXwtj15TxbRpCfGC1WayusWm8YH?cluster=devnet)), results_posted 12 with a 60 s deadline ([tx](https://explorer.solana.com/tx/4j8q8gfcV6dhb7X1MhvyG5EFxx3cEqVTHR2kAPaLjuK7fSUY5h2CBdhJsEPT81Sdp561bFhUXknvU3tzpH4Manbv?cluster=devnet)), referee_pass 20 ([tx](https://explorer.solana.com/tx/52naiW46WLT6AkJ7SYTN27mUjPWpgi6eZhRCS2XVuGt7kQoRTnKuWqkGGPUQq76tsJWR4QsrW6KDgabU3QUMqHZi?cluster=devnet)) | met (registered) |

Idea C's trial had posted no results when its 60-second `results_posted` stage expired, so that stage was
**refunded** to the buyer on devnet ([tx](https://explorer.solana.com/tx/5FtL36bLPvQhS7z8h8gq6ZGkiSS5LDkLJWd7gPnwrYdo7GP5q8G7DuqGdCLdysvmfSjoGtERZQCmVo8uA47dFDkg?cluster=devnet)),
while its other stages stay locked. Pre-orders: A ([tx](https://explorer.solana.com/tx/5s5ecg5DmSnycYEjyt2C3YpQbGrXkCfjZs3t1g9g1tGptpz71nR39pGMx41US2FXLaqJM4JQHRWqAAGBvbRsxnzB?cluster=devnet)),
B ([tx](https://explorer.solana.com/tx/4FLNgoLGJ1dnm1yyVgrbJ5WHveBrGpWdhzQWbDkP7pwVJAvcgj2MFPzTgdodcMviCD6G4V41XV2t2GxDW1ARmcjX?cluster=devnet)),
C ([tx](https://explorer.solana.com/tx/2yEjidBojssFJp1UFRoBmTtvphbzqAmhRngrDZzgZRHy3u8NfPCArNVEJDYJn4V3nB1UngrAwHLEWmDJPubbmhr9?cluster=devnet)).

These GitHub-checked stages are not released on devnet: that needs a GitHub-signed run of the referee repository's
workflow, which this sample does not fake. Their release audiences (with the evidence hash) are in the sample's output
file. The panel-checked stages below are released on devnet.

### Released on proof: idea C's stages checked by a 2-of-3 referee panel (15 Oct 2026)

`python -m knos.ideas.devnet_panel --wallets DIR --claim FILE --program ID --mint MINT --out FILE` locks two stages of
idea C as PANEL orders on the knos_pay 0.3.34 devnet test program `FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4`,
pinning three fresh devnet referee keys, two of which must agree. Then it reads both oracles live.

The payee is a wallet of the sample's own; ORCID's public test iD stands in for the researcher's.

| stage | oracle, read live | lock | referee verdicts | result |
|---|---|---|---|---|
| 1 | `trial_registered`: met | [tx](https://explorer.solana.com/tx/3xSno1arsASHsXMH3qvg8UkrZTLJQz6TcyuSCCpjefnk7ZxpiaPak7raDhWetZhoFYnEs1bvbgCJru4Lt1htTpav?cluster=devnet) | PASS 1 of 2 [tx](https://explorer.solana.com/tx/AqFurYcr6p5UfrLeJXELURJpjWPjK28Ycav2GPNirozX19dvPGht3D3eduMai5XcNjLHMAihhSumG8QjXLLdiPJ?cluster=devnet), PASS 2 of 2 [tx](https://explorer.solana.com/tx/3MJ9kGhWwKgkqGHDzeYRA7aycv8knci3oHHbWadvnARC5DVwj2pgbbndpWssuqjvjgKVVMFhELssGvAJ5VpCuuj8?cluster=devnet) | **released**: 8 test units to the payee `8wGdFZWAwi1N1xicR2yKPqr5K8nDcQHSarCXEEdfVLSd` |
| 2 | `results_posted`: not met (no results posted) | [tx](https://explorer.solana.com/tx/T6BVjke1xRyG9q8B5wmJF8KfeXuMe2uUnvuvwGpCnbPcmfbDJJpvAThMJK2dvp9RdXBLQuyF1cHHGhUgMwPxbcY?cluster=devnet) | FAIL 1 of 2 [tx](https://explorer.solana.com/tx/5xhvuNBZ1p6tKs99DP3VwpUPCf5AD6AwYGeRdMiFS1BD9ybBDd34NZaNeYyPfuGhrWqAjNkTPakhM5ppGFK8BFbN?cluster=devnet), FAIL 2 of 2 [tx](https://explorer.solana.com/tx/49iYkMoQrVynhGCkuTSYvQnChrxQi1Q9W25w8aHsn6u1ntukUzr8zVifoGwsrEr9BgZJ27zouSaHtTTiDRXjCTwC?cluster=devnet) | **refunded** to the buyer, amount and fee |

The test program is a separate devnet deployment of the 0.3.34 build, not the public knos_pay program: the public
program gets the panel path through a signed upgrade.

### Every stage kind, two more fields: materials and biology (15 Oct 2026)

`python -m knos.ideas.devnet_panel --wallets DIR --referees DIR2 --claim FILE --idea B --payee SPEC --program ID --mint MINT
--stages ... --review stage2=pass,stage3=fail --unlisted-panel --out FILE` runs the same code as `knos idea commit | sign |
release | refund`.

It handles every stage kind: automatic oracles are read live, and review stages are signed by each referee on a SYNTHETIC review
report. The referees' folder is refused when it is the buyer's folder or inside it.

In this sample one machine plays all three referees, so they are **not independent**, and their keys are off Knos's registry
(UNLISTED PANEL, labelled). The payee is `orcid:0000-0002-1825-0097@8wGdFZWAwi1N1xicR2yKPqr5K8nDcQHSarCXEEdfVLSd` (ORCID's test
iD standing in for the researcher). Each result is read back from the chain.

Materials, arXiv 1606.00335 (`knos-idea:c895e5d5ff037c0eab91fc4c42ea5445`, Materials Science):

| stage | oracle | lock | referee verdicts | result |
|---|---|---|---|---|
| stage1 | `preprint_posted` | [tx](https://explorer.solana.com/tx/4rFW6rRbWU5ZZVYLexYUQUgWLEGjn7kMhY55gNZ2TyrRHU7ZBUQqg7hu39pmoigNxHRTuNg6tkP8xgc6uVCPRinL?cluster=devnet) | PASS 1 of 2 [tx](https://explorer.solana.com/tx/3x5ny7MF7uVX49ANMw7Q3wrgEffYyXpuqgWbQetpP1UWtSXZ3RWmYmXGQH3yUnbcHGGGRrYiGTveX3kbEq24e6Q2?cluster=devnet), PASS 2 of 2 [tx](https://explorer.solana.com/tx/qJbLuvQUPsBn6nKAS2KZsjcm8cSRPQcAFor4Zh37FVTghjTr8YFnHd2fmcvTGaN2Ns3WGjjFTNDGQSkpdhCt89M?cluster=devnet) | **released** |
| stage2 | `referee_pass` | [tx](https://explorer.solana.com/tx/2Bf42bUDoDTv2KdSgjdrtaAVfpKi6KEkQi1pHWNKEgv6SSBCa9U3oJ4SYQi29HdJfLdvNG2nBgUmcnpTiCjtj6gz?cluster=devnet) | PASS 1 of 2 [tx](https://explorer.solana.com/tx/2RVQwM7dAwnzm9jR1PCJgj3CVX5kyFWGuHZjqCzM6D236yFBLoTNhknd4PeAyrzFYiZTaTKvfiEiQTkofs5ma6BZ?cluster=devnet), PASS 2 of 2 [tx](https://explorer.solana.com/tx/5FqH7ApKZwKxeAmqWrEKZx32aAkSR16BVj6eXJxDqzn4RMikm594uAJp92ZAPDLXVWHwrQf3uj8QGjvhjH2UEeGS?cluster=devnet) | **released** |
| stage3 | `lab_qc` | [tx](https://explorer.solana.com/tx/4h3NJt5hYDmj5HB2Y6LnqNTNAamiGBAgjKihCX7XtybV8kbzc4qnAKaF4ik3528xz23bcCYxDYfVdAGDMXtSbLYW?cluster=devnet) | FAIL 1 of 2 [tx](https://explorer.solana.com/tx/5FdDTg2KmZSZ7ZmAgVKY1gE2AqiBwjsAURZbZdkGSbjcLrNnRurj4MUaEXLvLeHSepcU1U4kYh1ZfCmYaHEi8DcV?cluster=devnet), FAIL 2 of 2 [tx](https://explorer.solana.com/tx/jKErifpLY7kZUoqhbqjqtHr7uuHNXDX7qoFq1vQdaVoNseUtYhiZ4PvAxFHauNK7HjfGpYJb3KQHKvnHG93ZRpd?cluster=devnet) | **refunded** |

Biology, PubMed 42806035 (`knos-idea:377dd46c8c894f1ac4b63e62c411d88a`, Biochemistry, Genetics and Molecular Biology), default stages of a published paper:

| stage | oracle | lock | referee verdicts | result |
|---|---|---|---|---|
| stage1 | `not_retracted` | [tx](https://explorer.solana.com/tx/2et4FD7qXR8yyPMMRd5HPhmNstzuX2vTrwG84mcuejGaisNpErqyDffHdZRiUmRyzsYwTUNSHGv6HD3o3igKqd8e?cluster=devnet) | PASS 1 of 2 [tx](https://explorer.solana.com/tx/qbKZhrCCRS5zbwpVcxtUtSm2ucu7YwBeEhHdzvpKU1ProL2tWMAAChboqP28MkUhjRXvXZ8qk2p9Lwo8P1FDYqB?cluster=devnet), PASS 2 of 2 [tx](https://explorer.solana.com/tx/hNMCks8TVre6kHH4vG6dagXbkr4rLPwqe17Ywqmr8yDT7ut7TVuNm6AxXjArnAwkHvvu84V19K1rPaox9HzsF1u?cluster=devnet) | **released** |
| stage2 | `referee_pass` | [tx](https://explorer.solana.com/tx/4FAquY9GRS3x1VkbpNi7rB5CtgAccF1TczuuNkXZHnC87TWwsRXeVDXCDcfRjfpW7b7u1K3XGEpeaoxyLTvbGt6b?cluster=devnet) | FAIL 1 of 2 [tx](https://explorer.solana.com/tx/3fq37Jk2hgKxAqa9Dkeiq9XUybncjLj4by786ZrvFaZwoUsngJHpCRG4LTmkYN2Wq9FSqLYYEN6C6Ueb8CgGiL2b?cluster=devnet), FAIL 2 of 2 [tx](https://explorer.solana.com/tx/5KVRPZNPNxmGRWq5nZYhBWn5hoNpttQZqVnPVj54bAgjaq7s5wmnSR56hCGAgYUDhAwn517BsJ2xgXNzxuLGSKhw?cluster=devnet) | **refunded** |
| stage3 | `lab_qc` | [tx](https://explorer.solana.com/tx/2r8tkYGrjrMgKshpg7W141DzjcYnxZwLmEhHFWht8PW2adxMhHNoQ7SmneQ6Pg5Q7AuFCyGFDFouSzJZ4ZyuA2HP?cluster=devnet) | PASS 1 of 2 [tx](https://explorer.solana.com/tx/4egTp51d31mf5ysd6j7n4wR6xs2XedaisU4KtYMwWuAYY7YET5srjFkGW1pUvdf2V8Fsuyj74GpHvzD6Atz4jZXY?cluster=devnet), PASS 2 of 2 [tx](https://explorer.solana.com/tx/5Q3ECQFZsh2Xhb7vGBFokdSqKmFAViLfdxuDr6yBjgEN4apW5EbR6YXqu4Xzf4AUR4s5Ks8d3MVa7wWkk7tcakyM?cluster=devnet) | **released** |

The payee's account held 8 test units before these runs (idea C's stage 1). It holds 56 after them:
8 + 20 (materials stages 1 and 2) + 8 + 12 (biology stages 1 and 3). The refunded stages paid it nothing.

## Limits

- The demand check's candidates are confirmed first-pick in the CLI, the MCP tool and the sample; a maker confirms each
  match in the demand-check page.
- A claim's statement for a paper is its title; extracting the quantitative claim (metric, value, interval) from full
  text is not built.
- `referee_pass` and `lab_qc` take M signed verdicts on a review or lab report file. The referee's own sealed-test
  verdict and the lab adapter's verdict are not yet carried into the stage automatically.
- Fields come from OpenAlex. When a work's primary topic names another field's subject (OpenAlex files Dias's
  superconductor papers under "High-pressure geophysics and materials", Earth and Planetary Sciences), the work's top
  level-0 concept decides (Materials science). Search results get the same field as `get`.
- OpenAlex's keyless daily budget is shared per IP: a hosted Knos needs its own key.
