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

The record's page on the site is `#record=<slug>`. The file and its page are free, and static. The price book's
Record line (0.10 USD a lookup, paid per call) exists as a server anyone can run and Knos does not host:
[section 5](#5-the-lookup-priced-for-machines).

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
    uses: drexthealpha/Knos/.github/workflows/supplier.yml@v0.3.19
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

`python -m knos.record_api <offer.json>` ([`examples/record_api`](../examples/record_api)) serves the same files
two ways: `/records/<slug>.json` free, and `/lookup/<slug>` for 0.10 test USDC a call, paid through the proposed
x402 `knos-order` scheme ([X402.md](X402.md), "Record"). An order buys fifty lookups, because the program takes no
order under 5.00; each call is signed by the wallet that funded the order, and a replayed call is refused. The paid
answer is the record with the order, the count and the time it was served: nothing the free file lacks. Knos hosts
no such server, no judge signs for lookups served, and nobody outside has paid for one. The rated supplier never
pays: the reader does.

## What this does not show

- A failed check is not always a failed test or a false claim; the interval and the dispute link stay beside a rate.
- Accepted means the agreed checks passed. It does not show that the work has no defect.
- Nothing recorded is not the same as nothing done.
- The supplier's memory is kept by whoever ran the judge: a record built from it is as complete as that memory.
