# The supplier's kit: a public record, a badge, one line to install, a receipt for the invoice

**The neutral meter for AI agent work: neither side keeps the count.**

The party whose work is rated (an agent builder, an agency, a vendor) gets four things from Knos and pays for none of
them. The buyer still pays (the price book in [PILOT.md](PILOT.md)); the rated party never pays, and a record cannot
be bought or changed for money. One limit, first: Knos wrote these records and nobody outside Knos has reviewed them.

| what | command | what it writes |
|---|---|---|
| the record | `knos record build <supplier>` | `docs/records/<slug>.json`, and its badge beside it |
| the badge | `knos badge record <slug>` | an SVG, and the Markdown line that links it to the record's page |
| the install | one `uses:` line (below) | the free check on every pull request, posted once, with its receipt |
| the receipt for an invoice | `knos record receipt <acceptance receipt file>` | one PDF page and its JSON |

The record's page on the site is `#record=<slug>`. The file and its page are free, static and unsigned, and each
says the day it was built. The price book's Record line (0.10 USD a lookup, paid per call) is a server anyone can run
and Knos does not host; its answer adds a signature with an expiry, a summary and the history a supplier grants:
[section 5](#5-the-lookup-priced-for-machines). Record budget: zero revenue until someone buys it.

## 1. The record

`docs/records/<slug>.json`, schema `knos.supplier-record/1`. It has two parts, kept apart, and each says where it
came from.

**`orders`: work settled through Knos.** Seven counts: accepted, rejected, insufficient evidence, disputed, appealed,
overturned on appeal, reverted. Each count is `{"n", "from", "evidence"}`: `n` is the length of `evidence`, and
`from` names its source.

| source | read with | what it counts | the evidence behind a count |
|---|---|---|---|
| the events log ([EVENTS.md](EVENTS.md)) | `--events <log>`, `--id <the supplier's name in the log>` | deliverables: each once, under the verdict it has after every correction; an event a correction voided is `reverted` | the event's id, its line and that line's sha256 in the chain, and where the issuer's evidence is (a transaction, a batch and its root) |
| the supplier's memory in the Sibyl engine (`knos.proof.history` `supplier_record`, `appeals`) | `--memory <folder>`, `--repo owner/repo` | pull requests accepted and rejected under funded orders, appeals, rejections overturned | the pull requests, and an appeal's id |

Accepted and rejected come from the log when it holds the supplier, and from the memory otherwise: they are never
added, because both would count the same work. Insufficient evidence, disputed and reverted are the log's; appealed
and overturned are the memory's. `orders.parts` says which sources were read, the log's head and the repositories
recalled. `orders.sample`, `orders.period` and `orders.category` stand beside the counts.

**`public`: from public pull requests, not from Knos orders.** For an agent the Agent PR Index measures
([INDEX.md](INDEX.md)), its row of the newest week: the merged pull requests that claimed passing tests (`sample`),
how many had a failed check, the share, its 95% Wilson interval, the weeks read, and the link that disputes the row.
`scripts/agent_pr_index.py board` writes these files for every agent of the index, from the index alone; its
`--check` fails when one is behind.

Nothing in the file is a score. `sha256` is the SHA-256 of the file's canonical JSON without that field
(`knos.record_page.check`). The file is not signed: the evidence a count links to is.

What the records hold today: one file for each agent the index ranks, and each holds its index row only. The
`public` part is that row: the merged pull requests that claimed passing tests, how many had a failed check, the
interval, the weeks read. Every count of `orders` is zero with sample zero, and the file says so: no work has been
settled through Knos for any ranked agent, and **no record holds a Knos order of an outside supplier yet**. A
record is therefore not yet something to price a supplier on ([ADVANCE.md](ADVANCE.md)).

## 2. The badge

`knos badge record <slug>` draws the record as an SVG in the drawing every Knos badge uses (`knos.badge`), with no
script, no link and no font of its own. `web/badge.js` `recordBadgeSvg` writes the same bytes.

- With work settled through Knos: `Knos-verified: 14 accepted, 0 reverted, sample 16, 2026-07 to 2026-09`. Green
  only when something was accepted.
- Without: `Knos record: no Knos orders yet; public PRs: <failed> of <sample> had a failed check, week of <Monday>`.
  Grey.

The sample is always in the badge. The command prints the Markdown that links the picture to the record's page; it
goes in a README or a pull request's description.

## 3. One line to install

In the supplier's own repository, `.github/workflows/knos-supplier.yml` ([examples/knos-supplier.yml](../examples/knos-supplier.yml)):

```yaml
name: knos supplier check
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
permissions: {}
jobs:
  knos:
    permissions:
      contents: read
      checks: read
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/supplier.yml@v0.3.23
```

The last line is the install. It runs the free check on every pull request and none of the pull request's code,
posts the result as one comment that later runs rewrite, and attaches the receipt as the artifact
`knos-receipt-<pull request>` (`knos.check-receipt/1`: the repository, the pull request, the head commit, the result,
the judge's evidence and its sha256). A pull request from a fork runs with a token that can only read: no comment is
posted then, and the result is the job's summary and conclusion. That receipt is the check's own record, signed by
nobody; it is not an acceptance receipt and nothing is paid on it. Name the workflow by a full commit sha instead of
the tag when a moved tag must not change what runs.

## 4. The receipt to send with an invoice

`knos record receipt <file> [--invoice INV-7] [--out path]` reads one acceptance receipt ([RECEIPT.md](RECEIPT.md),
version 2 or later) and writes one A4 page and its JSON (`knos.invoice-receipt/1`): what was agreed (the order, the
terms' hash, the amount), what was delivered (the repository, the pull request, the commit), what was accepted (the
verdict, the checks, when, what was paid), by which evaluator (its kind and version, the issuer that signed for it,
its independence), and the evidence hashes. A receipt that does not check gets no page. The page names the one
command that checks the receipt file with no network:

```
knos receipt <file>
```

The page restates the receipt; the receipt file is the evidence, and the supplier's finance operator sends both.

## 5. The lookup, priced for machines

`knos record serve <offer.json>` (`python -m knos.record_api`, [`examples/record_api`](../examples/record_api))
serves the records two ways: `/records/<slug>.json` free, and `/lookup/<slug>` for 0.10 test USDC a call, paid
through the proposed x402 `knos-order` scheme ([X402.md](X402.md), "Record"). An order buys fifty lookups, because the
program takes no order under 5.00; each call is signed by the wallet that funded the order, and a replayed call is
refused. The reader pays. The rated supplier never pays, for its record or for a grant.

**budget: zero revenue until someone buys it.** Knos hosts no such server, no judge signs for lookups served, and
nobody outside has paid for one. The paid answer below is built and tested here; it has not been served on devnet.

### The free file and the paid answer, row by row

| | the free file | the paid answer |
|---|---|---|
| where | `docs/records/<slug>.json`, the page `#record=<slug>` | `GET /lookup/<slug>` on a server someone runs |
| price | free | 0.10 test USDC a lookup, a pack of fifty an order |
| who pays | nobody | the reader; never the rated supplier |
| the record | the counts, each with its evidence | the same file, byte for byte, inside the answer |
| signature | none: `sha256` of the file only | Ed25519, by a key the operator supplies (`--key`); with no key the answer says it is unsigned |
| freshness | the day it was built (`as_of`) | the cluster time and slot the server read, when it produced the answer, and when the answer expires (one hour unless the operator sets `--ttl`) |
| checked with | `knos.record_page.check` (the hash) | `knos record verify <answer>`: no network; prints fresh, stale, unsigned or invalid |
| summary | none: the reader works out rates | `knos.record-summary/1`: every count as `k` of `n` with its share and 95% Wilson interval, the same denominators for every supplier |
| history | none | four fields, each only with the supplier's signed grant to this reader; otherwise `not granted` |
| availability | a static file in a public repository | what the operator promises, stated in the answer: nothing, on devnet; `knos record serve --health` |
| revenue | none | budgeted at zero |

### Signed freshness

The answer (`knos.record-answer/1`) is signed over the record's `sha256`, the events log's head when the record was
built from one, the cluster time and slot the server read from the Clock account, `produced` and `expires`. The three
times follow the shape of a certificate status answer ([RFC 6960](https://www.rfc-editor.org/rfc/rfc6960): thisUpdate,
producedAt, nextUpdate): the reader holds the answer to its own clock.

```
knos record verify answer.json --operator <the operator's public key>
```

| it prints | when | exit |
|---|---|---|
| fresh | the record hashes to what was signed, the summary is the record's, the signature is the key's, and the time is inside `produced` to `expires` | 0 |
| stale | all of that, and past `expires` | 1 |
| unsigned | the server had no key, or the file is the free record | 1 |
| invalid | anything was changed, the key is not the operator named, or the times do not stand | 1 |

The signature shows which key answered and when. It does not show that the operator's records are complete: the
operator serves the files it was given. Name the operator's key with `--operator`; without it the command says whose
key signed and asks the reader to check it.

### Permissioned history

`knos record history <supplier> [--events <log>] [--id <name>] [--memory <folder>] [--repo owner/repo] [--times <file>]`
writes `<slug>.history.json` (`knos.record-history/1`). It is never put in the free folder. Its four fields:

| field | what it holds | read from |
|---|---|---|
| `per_buyer` | the counts for each repository an order was funded in (its owner is the buyer), and by month | the supplier's memory in the Sibyl engine; the events log, which names no buyer, by month |
| `disputes` | each disputed deliverable; each appeal with its state, its reason and how it ended | the events log; `knos.proof.history` `appeals` |
| `corrections` | every correction that names one of the supplier's events: what it changed and why | the events log |
| `time_to_accept` | the count, the fastest, the median, the ninetieth percentile, the slowest, four buckets | a times file the supplier gives: the events log keeps no times |

The supplier releases fields to one reader with a grant it signs (`knos.record-grant/1`):

```
knos record grant <slug> --reader <the reader's wallet> --field disputes --field corrections --key supplier.json --days 30
```

The reader sends the grant with its paid call (header `Record-Grant`). The server releases a field only when the
grant is signed by the key its operator holds for that supplier (`--suppliers`, a file of slug and public key), names
the wallet that paid, names the field, and is in force. Otherwise the field reads `not granted`, with what it would
hold and never the data. The operator decides which key is a supplier's: nothing on chain binds the two yet.

### The summary

One function for every supplier (`knos.record_answer.summary`): accepted, rejected, insufficient evidence and
disputed over deliverables with a verdict; reverted over deliverables on record; overturned over rejections appealed;
failed checks over merged pull requests that claimed passing tests. Each is `{k, n, of, share, ci95}`, the interval
computed as the Agent PR Index computes it ([INDEX.md](INDEX.md)). `score` is `null`: nothing is weighted or added
into one figure. Not a rating of defect-free work.

### Availability

The answer carries the operator's promise. The default, and the only one on devnet: uptime none, support none,
retention none. An operator states its own in the offer's `availability`. `knos record serve --health` (and
`GET /health`) says whether the records are readable, whether the chain answers, whether answers are signed and by
which key, and whether the count of each order survives a restart; it exits 0 only when the server can answer.

## What this does not show

- A failed check is not always a failed test or a false claim; the interval and the dispute link stay beside a rate.
- Accepted means the agreed checks passed. It does not show that the work has no defect.
- Nothing recorded is not the same as nothing done.
- The supplier's memory is kept by whoever ran the judge: a record built from it is as complete as that memory.
