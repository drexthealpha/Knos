# One log of events

Knos records work in several modes. Each refuses its own repeats, and none sees the others.

| Mode | What it writes | What it refuses on its own |
| --- | --- | --- |
| `record` | one evaluation, one transaction, one Mark account | the same evaluation again, while the Mark exists |
| `batch` | a month's evaluations under one Merkle root | the same id twice in one batch |
| `settle` | a paid order or bounty | paying one milestone twice |
| `shadow` | an invoice set against GitHub's record | the same pull request or issue twice in one invoice |
| `import` | a file somebody hands over | nothing |

So the same evaluation can be recorded singly in one week and sit inside a batch the next, and a deliverable can
be billed on two invoices. `src/knos/events.py` is the one place that says "this was already counted".

## What an event is

One line of a JSON Lines file, written in the canonical form (`knos.ledger.canon`: keys sorted, no spaces).

| Field | Meaning |
| --- | --- |
| `id` | what the event is. An evaluation, an invoice line or a settlement carries its id from `src/knos/ids.py`. An acceptance (`acc_`), a correction (`cor_`) and an acknowledgement (`ack_`) are built the same way under a tag of their own. Never derived from when or how the event arrived. |
| `kind` | `evaluation`, `acceptance`, `invoice_line`, `settlement`, `correction`, `acknowledgement` |
| `source` | the mode it arrived by: `record`, `batch`, `settle`, `shadow`, `import` |
| `deliverable`, `evaluation`, `invoice_line`, `settlement` | the four ids, where they apply |
| `verdict` | accepted, rejected, insufficient_evidence, disputed, or empty |
| `amount`, `unit` | a whole number and what it counts |
| `supplier`, `month` | who, and the month a statement looks for it in |
| `evidence` | where the issuer's evidence is: a transaction, a batch and its root, a shadow statement's hash and line |
| `corrects`, `void`, `reason` | a correction: the event it names and what changes |
| `ack` | an acknowledgement: party, last line, head hash, and the signed token itself |
| `seq`, `prev` | the line's number and the SHA-256 of the line before (64 zeros for the first) |
| `first` | on a repeat: the line that counts |

## One way in

`ingest(log, events)` is the only function that adds to a log. Four outcomes:

1. **New id.** Appended and counted.
2. **Same id, same content, another source.** Appended as a repeat that names the line that counts. Counted
   once; both sources stay on record (`knos events dupes`).
3. **Same id, different content.** A conflict. Refused, reported with the fields that differ, written to
   `<log>.refused.jsonl`, and not added to the log.
4. **The very same arrival again** (same id, source and evidence). Nothing is written. A retry is free.

"Content" is what the event states: kind, the four ids, verdict, amount, unit, supplier. The month and the
evidence are where and when, not what. An acceptance does not state which evaluation carried it, so ten
evaluations of one deliverable give ten evaluations and one acceptance.

Each mode has an adapter that turns its records into events with the same ids: `from_records`, `from_ledger`,
`from_audit`, `from_shadow`, `from_import`.

## Corrections

A correction is an event: it names another event and says what it is from now on (a verdict, an amount, or
void). The line it names is never touched. The latest correction of an event holds. A statement names the log
head it was made at, so a later correction gives a later statement and never a changed one.

## Numbers, gaps and closing a month

A root commits to what was supplied. It cannot say that something was not. So a sender numbers what it sends, from
0, per buyer, supplier and month, and the number travels in `evidence`:

    batch:<buyer>:<supplier>:<yyyymm>.<number>:<root>...      the batch mode: the batch's seq
    sent:<buyer>:<supplier>:<yyyymm>.<number>[:anything]      any other mode whose sender numbers what it sends

`knos events gaps LOG` names every number below the highest that arrived that is not in the log, and exits 1 while
one is unexplained. With `--last <buyer>:<supplier>:<yyyymm>.<n>` it also checks up to the last number the sender
says it sent.

A gap ends when the missing arrival is ingested, or when a correction explains it:

    knos events gaps LOG --explain <buyer>:<supplier>:<yyyymm>.<n> --reason "the run was cancelled"

That appends a correction whose `corrects` is `gap:<buyer>:<supplier>:<yyyymm>.<n>`, void, with the reason. It is
refused when the number did arrive. It counts once a party has acknowledged a head after it: the acknowledgement's
signed token is what signs the correction. `knos events close LOG --month YYYY-MM` refuses the month while a gap
has neither an arrival nor an acknowledged correction.

One deliverable id, ever. An acceptance takes its id from its deliverable, so the same deliverable accepted again
in a later month is a repeat, and at another amount a conflict. A second invoice line for it is a `duplicate` in
its month's statement. `knos events dupes` also names every deliverable with more than one counted invoice line or
settlement, across months.

Keeping the evidence, and checking it with no Knos: [RETENTION.md](RETENTION.md).

## Acknowledgements

The other party signs the log up to a head. The mechanism is the one a month's close already uses
(`knosm:close:` in `src/knos/ledger.py`): a GitHub Actions token, RS256, checked with no network by
`knos.bundle.rs256`, whose audience names what is signed:

    knosm:ack:<GitHub owner id>:<last line>:<head hash>

`knos events ack LOG --as <id>` prints the audience; a job in that owner's repository asks GitHub for a token
with it; `knos events ack LOG --token FILE --keys JWKS` checks it and appends the acknowledgement. The token is
kept in the log line, and the keys it used in `<log>.jwks.json`.

After that, a log in which that line no longer has that hash fails `knos events verify`, even when whoever
changed it recomputed every hash after the change: they cannot make the token name another head. No program
reads this audience. It is checked off chain.

## Each party signs the month, and when a month closes

A token in the log says that one GitHub owner signed a head. It does not say which side of the contract that owner
is, and nothing stopped one side from adding a line the other never saw. So each party also signs the month itself,
with an Ed25519 key its Knos Terms 3 document names (`window.period_close`: `buyer_key`, `supplier_key`,
`silence_days`). The signed text puts one fact a line, as a transparency log's signed note does and as a witness's
cosignature of a checkpoint does ([C2SP tlog-cosignature](https://github.com/C2SP/C2SP/blob/tlog-cosignature/v1.0.0/tlog-cosignature.md)):

    knos-period-ack/v1
    role supplier
    month 202610
    last 41                 the last line of the log the party read
    head <hash of line 41>  it commits to every line before it
    root <sha256>           over the hashes of the month's lines up to line 41
    events 12               how many lines of the month that is
    terms <sha256>          the terms that name the keys
    day 2026-11-03          the signer's own word: no clock signs it

A month is **closed** only when the buyer and the supplier signed the same last line and root, or when one of them
signed, the terms allow one party to close after `silence_days` without an answer (0: never), and that party signed
a closure (`knos-period-close/v1`, the same lines plus `acknowledged <day>` and `silence_days N`) dated that many days
or more after its acknowledgement. After that, three things are **named discrepancies**:

| Name | What happened |
| --- | --- |
| `missing-after-ack` | lines a party acknowledged are no longer in the log |
| `changed-after-ack` | the acknowledged line now has another hash, or the month another root |
| `event-after-close` | a counted event of a closed month was added after the line it closed at (a correction may still arrive) |

    knos events sign LOG --month YYYY-MM --role buyer|supplier --key KEY.json --terms TERMS.json --on YYYY-MM-DD [--out FILE]
    knos events sign LOG ... --closing MY-ACK.json            # a closure after the silence the terms allow
    knos events close LOG --month YYYY-MM --terms TERMS.json --ack BUYER.json --ack SUPPLIER.json

The rule is written once, in `src/knos/standalone_verify.py` (`periods`; Ed25519 as RFC 8032 section 6 writes it,
in the standard library: [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032.html)), and `knos.period` reads it; keys
are signed with solders. An evidence archive keeps the files under `acks/`, and its `verify.py` checks them against
the archived log and terms (docs/reference/RETENTION.md). Tests: `tests/test_events_period.py`.

## Statements from the index

The log keeps three indexes as it grows: by deliverable, by month and by supplier. A month's statement reads
that month's lines only, and finds a deliverable's verdict and its earlier invoice lines by key, in whatever
month they are. Each invoice line is `agreed`, `disputed`, `duplicate` or `insufficient_evidence`.

Measured with `python scripts/events_bench.py --events 100000` (100,000 synthetic events over 12 months and 20
suppliers, 3,717 of them repeats, a 44.8 MB log; 2 shared cores of an Intel Xeon at 2.10 GHz, CPython 3.11, one
run, other work running on the machine):

| Step | Seconds |
| --- | --- |
| ingest 100,000 events (ids checked, duplicates found, hashes chained, index built) | 6.81 |
| read the log back and verify every line (the index is rebuilt in the same pass) | 6.55 |
| one month's statement from the index (8,348 events, 2,469 invoice lines) | 0.059 |

The index is not stored. It is rebuilt whenever the log is read, because every line is hashed then anyway. So
the cost of a statement in a new process is the read (6.55 s here) plus 0.059 s per month asked for. The
figures are from one run on a busy machine; run the script for your own.

Once on the chain's own lines, on 6 Oct 2026: `knos audit export --owner drexthealpha --from 2026-09-01 --to 2026-10-06`
(the escrow's log lines on devnet, 52 lines, all of them the founder's own test orders and bounties) was taken in with
`--from settle`: 45 paid lines counted. Taken in again: 0 counted, 45 seen before from this source. `knos events
verify`: 45 lines check, acknowledged by nobody. `knos events dupes`: none, since one mode wrote every line. None of
the 52 is the playground's: its one issue was opened while devnet ran a `knos_pay` older than 2.1, so nothing was
funded there ([PLAYGROUND.md](PLAYGROUND.md)).

## Commands

    knos events ingest LOG FILE --from record|batch|settle|shadow|import [--month YYYY-MM] [--invoice NAME]
    knos events verify LOG [--keys JWKS] [--head HASH]        # or a folder written by export
    knos events ack LOG --as OWNER_ID                         # print the audience to sign
    knos events ack LOG --token FILE --keys JWKS              # add a signed acknowledgement
    knos events dupes LOG
    knos events gaps LOG [--month YYYY-MM] [--last B:S:YYYYMM.N] [--explain B:S:YYYYMM.N --reason WHY]
    knos events close LOG --month YYYY-MM [--last B:S:YYYYMM.N] [--terms TERMS --ack FILE ...]
    knos events sign LOG --month YYYY-MM --role buyer|supplier --key KEY --terms TERMS --on DAY [--closing ACK]
    knos events statement LOG --month YYYY-MM [--supplier S]
    knos events export LOG --out DIR

`export` writes the log, the acknowledgements and their keys, the repeats, what was refused, the index and each
month's statement, with a manifest of hashes. `knos events verify DIR` reads the log again and rebuilds every
other file from it; a file that differs is named.

## One definition of an event's hash

An evaluation that arrives from a format 2 batch carries, in `evidence`, the batch, its root and the event's hash:
`batch:<buyer>:<seller>:<yyyymm>.<seq>:<root>:event:<64 hex>`. That hash is the leaf of the batch's tree, computed by
the one function both modules use (`knos.ledger.event_hash`; `knos.events.event_hash` is the same function, in hex),
so the log and the batch cannot disagree about what an event is. The bytes it hashes are in
[METER.md](METER.md#what-a-root-commits-to-two-formats). An evaluation from a format 1 batch has no such hash: that
root binds the set of evaluation ids, the count, the accepted count and the value; not which evaluation was accepted.

## What this proves

- A removed, reordered or edited line is found, from the file alone, when anything follows it in the chain.
- An event is counted once per log, whichever modes it arrived by, and every arrival is on record.
- Two different claims under one id never both enter the log.
- A range a party acknowledged has not changed since, as far as that party's signature is checked against keys
  you trust. Whether a JWKS file really holds GitHub's keys is yours to check once (`docs/reference/OIDC.md`).
- A statement is the same bytes for whoever holds the same log.

## What it does not prove

- **Nothing here is on chain.** Uniqueness is enforced by this layer and by both parties' acknowledgements.
  The on-chain batch root commits to a set. It does not prove the set is complete, and it does not prove the
  set shares nothing with another batch or with the single records (`docs/reference/METER.md`, "What the count proves and what it does not").
- **That every relevant event was supplied.** The log holds what was ingested, and a batch root commits to what was
  put under it. An event nobody supplied is in neither, and no hash can know. Completeness comes from both sides
  submitting independently and reconciling: each party keeps its own ledger, `knos meter reconcile` reports the
  omissions, duplicates, conflicts and corrections between the two, and each acknowledges the other's log.
- **Lines removed from the end.** A shorter chain is still a chain. They are found only against a head you
  kept: `--head`, an export's manifest, or an acknowledgement the other party holds.
- **A log rewritten whole before anyone acknowledged it.** Hashes and all, by whoever holds the file. Until a
  second party has signed a head, the log is one party's file.
- **A dropped acknowledgement.** The party that signed holds the token and the head; the file alone does not
  show that an acknowledgement was cut off its end. A month signed under `window.period_close` is not closed
  without both signatures (or a closure the terms allow), so a dropped one leaves the month open, and says so.
- **Who holds a key, and on which day it signed.** The terms name the keys; the day is the signer's word.
- **That the content is true.** A wrong verdict ingested once is counted once.
- **Numbers past the last one that arrived.** A gap is a number below the highest seen. The end of a run is
  checked only against the last number its sender states (`--last`).
- **Two writers without the lock.** `knos events ingest` holds `<log>.lock` while it reads and appends. A program
  that appends without it can break the chain, and `verify` says so.
- A month is where an event's first arrival put it. A repeat that names another month does not move it.

## Why there is no on-chain marker per event

A marker that makes an event unique on chain is an account that exists for as long as the event must stay
unique. Solana holds a minimum balance against every account:

    minimum balance = (128 + data bytes) x lamports per byte

Source: [Solana, "Reduced rent" (SIMD-0437), updated September 2026](https://solana.com/upgrades/reduced-rent).
The rate was 6,960 lamports per byte and is being lowered in five steps (6,333, then 5,080, 2,575, 1,322 and
696; the last three are expected with Agave 4.4). Devnet and mainnet both charged 5,080 on 4 Oct 2026, read from
the nodes ([METER.md](METER.md), "What an evaluation costs in each mode"). The meter's own marker, the Mark
account, is 88 bytes (`MARK_LEN` in `programs-v2/knos_meter/src/state.rs`), so a marker is held against
128 + 88 = 216 bytes. One SOL is 1,000,000,000 lamports. The USD column uses the 121.50 USD per SOL that
METER.md sources for the same day.

| Lamports per byte | One 88-byte marker | USD | 100,000 events | 1,000,000 events |
| --- | --- | --- | --- | --- |
| 6,960 (the old rule) | 1,503,360 lamports | 0.1827 | 150.3 SOL | 1,503 SOL |
| 5,080 (both clusters, 4 Oct 2026) | 1,097,280 lamports | 0.1333 | 109.7 SOL (13,332 USD) | 1,097 SOL (133,320 USD) |
| 696 (the target of the last step) | 150,336 lamports | 0.0183 | 15.0 SOL (1,827 USD) | 150 SOL (18,266 USD) |

At today's rate the deposit for one marker is about 67 times the 0.002 USD an evaluation the price book proposes (0.1333 / 0.002); the deployed knos_meter charges 0.05 after 10,000 free. A marker with
no data at all is still held against 128 bytes: 890,880, 650,240 and 89,088 lamports at the three rates. Ask a
node for its cluster's figure: `getMinimumBalanceForRentExemption` with the size.

The balance is a deposit: it comes back when the account is closed. A closed marker no longer stops a repeat.
That is the trade the single mode already makes: its Mark is closed after its month (`CloseMark`), so the
chain refuses a repeat within the month and not after. A marker kept for good is a deposit never returned, plus
one transaction per event, which is the cost the batch mode exists to avoid. So Knos does not claim on-chain
uniqueness across batches and single records. It claims this log, and two signatures on its head.
