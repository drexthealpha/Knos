<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# Knos Record: a history whose edits show

**In plain words.** Every time Knos checks something (a research claim, an experiment, a verdict, a cheat it caught,
a refusal, a payout or a refund), it writes one line to a public file. Each line carries the fingerprint (hash) of the
line before it, so changing any old line breaks every line after it.

Every so often, one fingerprint for a whole batch
of lines (a Merkle root) is written into a Solana devnet transaction. Anyone can then recompute that fingerprint from
the file and compare it with the chain: `knos record verify`.

This page is about the journal in `src/knos/record/`. A supplier's public record page and its paid answer are a
different thing, described in [SUPPLIER.md](SUPPLIER.md).

## What a line is

One JSON object per line in `journal.jsonl`:

| field | meaning |
|---|---|
| `v` | format version, `1` |
| `seq` | the line's number, from 0 |
| `ts` | UTC time it was written |
| `kind` | `claim`, `paper`, or an event: `experiment`, `verification`, `verdict`, `cheat`, `refusal`, `payout`, `refund`, `funding`, `graduation`, `split`, `anchor` |
| `tier` | where Sibyl's memory engine keeps it: `WARM` (claim), `REFERENCE` (paper), `COLD` (every event) |
| `claim` | the claim or paper id the line is about, or null |
| `domain` | a short field name such as `ml`, or empty |
| `payload` | the facts: spec hash, pass or fail, cheat type, amount in the mint's smallest unit, devnet transaction signature |
| `prev` | the hash of the line before (`0` x 64 for the first) |
| `hash` | sha256 of the line's canonical JSON (sorted keys, no spaces) without `hash` |

The record is public, so a line is refused before anything is written when its payload looks like a secret. That
means a field named like a key, token, password or e-mail; a GitHub, Slack, AWS or API token; a PEM block; or a
signed token (JWT).

It also means an e-mail address; a home-folder path; an array of 32 or 64 bytes; or 64 bytes in base58 or hex under a
name that does not say it is a signature or a hash.

Sample data says `"synthetic": true` in its payload.

## Sibyl holds every line too

Knos remembers through Sibyl's memory engine and nothing else (`tests/test_sibyl_is_load_bearing.py`). The record
uses three of its tiers, in Sibyl's local store `sibyl.db` beside the file (tenant `knos-record`):

- **WARM**: one entity per research claim (category `record_claim`), holding its latest state.
- **COLD**: one journal event for every line, claims and papers included. This is the second witness.
- **REFERENCE**: one reference document per paper (`record:paper:<id>`).

A line goes to Sibyl first and to the file second. Without Sibyl's package there is no record at all.

Why it matters: cutting lines off the end of the file breaks no hash. Held to Sibyl's journal, the cut is caught;
with no memory, or with Sibyl's store deleted, it is not (`tests/test_record_verify.py`). An anchored root catches the
same cut once an anchor covers those lines.

## Anchoring a batch on Solana devnet

`knos record anchor [DIR] --keypair wallet.json` computes the Merkle root of every line since the last anchor (built
as Certificate Transparency builds one, RFC 9162 section 2.1), puts it in one transaction of Solana's SPL Memo program
(`MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`), signed by the anchoring wallet, and appends an `anchor` line naming
the transaction:

```
knos-record:v1 root=<merkle root> first=<seq> last=<seq> head=<hash of line last>
```

No Knos program is used or changed. Devnet or a localnet only; mainnet is refused. Anchoring is never automatic: the
keeper of a record decides when. `--dry-run` shows the memo and sends nothing.

`knos record prove SEQ [DIR]` prints the audit path that shows one line is in its anchored batch, without the rest of
the file.

## Checking a record: `knos record verify [DIR | journal.jsonl]`

1. Every line parses, has exactly the fields above, sits at its `seq`, links to the line before, and hashes to what
   it says. Its tier matches its kind. Its payload passes the public-record check.
2. Each anchor covers the lines right after the previous one. The Merkle root recomputed from those lines is the root
   it states.
3. Each anchor's transaction is read from the cluster. It must exist, must have succeeded, must be signed by the
   wallet the line names, and its Memo instruction must be exactly the recomputed memo. `--offline` skips this, and
   the report says the chain was not read. A transaction that cannot be read is a failure, never a pass.
   Whether on chain or offline, the wallet that signed each anchor must be a trusted anchoring key. That key comes from
   outside the file: `--signer KEY` (repeat it), else `KNOS_RECORD_SIGNERS`, else the key pinned in
   `src/knos/record/anchoring.py`. Today the pinned key is the build's own devnet wallet
   `8aukezen9sAALWShcZKK3hi8WawBi4vR6qmLf764PGBv`. Without the pin, anyone could rewrite the whole file and anchor it
   again with a wallet of their own, and every hash and root would agree.
4. When Sibyl's store is beside the file, every line Sibyl's journal holds must be in the file, unchanged, and the
   other way round. Each claim entity and paper reference must point at its latest line. A public copy has no store
   beside it. It is checked by 1 to 3, and the report says Sibyl was not consulted.

Exit code 0 when every check passes, 1 otherwise. `--json` prints the report.

**Verifying your own record.** A record you anchored with your own wallet is not signed by Knos's pinned key, so a
plain `knos record verify` fails it on purpose (anyone could otherwise re-anchor a rewritten file). Name the key you
trust, which is the public key of the wallet that anchored it:

    knos record verify DIR --signer <your anchoring public key>
    KNOS_RECORD_SIGNERS=<key>[,<key>...] knos record verify DIR

The failure message names the anchor's signer and prints this flag with it. Trust that key only if it is yours, or
the key of someone you choose to believe.

`knos record anchor`, `journal` and `prove` need something after them (a folder, a seq or an option). On its own,
`knos record anchor` is still the record of the GitHub login `anchor`. `python -m knos.record anchor` needs no argument.

## The sample record (synthetic)

`src/knos/record/demo/journal.jsonl` is a synthetic record of ten lines: a paper, a claim, two experiments, a caught
cheat (`test_edited`), its refusal, a verdict, a payout line (synthetic: no transaction was sent for it), the claim's
new state, and an anchor. Its first nine lines are anchored on devnet:

| | |
|---|---|
| transaction | [`1C7bCGM7jHrj4XEkiWQKq3D4qYYj5mKxneGENJBjUoEEMzkQWHmRoaMMinkXePEpfS2A3E4vdWyfgEoB3m5qjFy`](https://explorer.solana.com/tx/1C7bCGM7jHrj4XEkiWQKq3D4qYYj5mKxneGENJBjUoEEMzkQWHmRoaMMinkXePEpfS2A3E4vdWyfgEoB3m5qjFy?cluster=devnet) |
| slot | 510678984 |
| Merkle root of seq 0..8 | `2817c4837adc981d73cd676c73930deb998cde88e07fb27ba088ec005e54b599` |
| signer (devnet wallet) | `8aukezen9sAALWShcZKK3hi8WawBi4vR6qmLf764PGBv` |

Check it yourself: `knos record verify src/knos/record/demo` (reads devnet), or `--offline` to recompute only.

## For code in Knos

```python
from knos import record
record.claim("claim-42", {"title": "...", "spec_hash": "..."}, domain="ml")
record.append("verdict", {"spec_hash": "...", "passed": False, "cheat": "test_edited"}, claim="claim-42")
record.paper("arxiv:2401.00001", {"title": "...", "sha256": "..."})
record.anchor(keypair="wallet.json")
record.verify()
```

Every part of Knos writes the record only through `append`, `claim` and `paper`. The default folder is
`$KNOS_RECORD_DIR`, else `~/.knos/record`.

## What this is not

The record does not stop edits. It makes them show, to someone who checks, within these limits:

- An anchor shows that a batch of lines existed in this order at the slot of its transaction. It does not show that
  what a line says is true. The referee and the checks that wrote the line are what vouch for that.
- Whoever holds a trusted anchoring key can rewrite the file and anchor the new version. The pin moves trust to that
  key; it does not remove it. Anyone can list every transaction the key signed, so two different anchored histories
  can both be seen. Today one key, the build's devnet wallet, anchors this record.
- A record with no anchor proves nothing about its past: a rewritten copy would verify the same way. The report says
  when there is no anchor.
- Lines written after the last anchor have only the file's hashes and Sibyl's journal behind them. Cutting them from
  the end of a public copy, which has no Sibyl store beside it, is not caught until the next anchor.
- Nobody outside Knos has reviewed this code.

## Retention: what a root proves, who keeps what, and what is left if Knos disappears

A batch's root (one fingerprint of all its lines, a Merkle root, written on chain) proves one thing: a line you hold is among the lines that were put under
that root, and has not changed since. It is a commitment. It is not a copy and it is not a count of what should
have been there.

| A root proves | A root does not prove |
| --- | --- |
| a line you hold was committed to, byte for byte | that anyone still holds the lines (availability) |
| the count, the accepted count and the value signed with it | that every evaluation was supplied (completeness) |
| nothing under it was changed afterwards | that the same deliverable is not also under another root, in another month |

Each right-hand cell is answered off chain, by something a second party can check without Knos. This page says by
what, and names the test behind each statement.

### Availability: every party keeps the archive

`knos archive make OUT.zip --events LOG --ledger FILE [--statement FILE] [--token FILE] [--receipt FILE] [--terms
FILE] [--close FILE] --keys JWKS --keys-read YYYY-MM-DD` writes one file:

| In the archive | What it is |
| --- | --- |
| `events/log.jsonl` | the log of events (`src/knos/events.py`), with the acknowledgements signed into it |
| `statements/events-<yyyymm>.json` | each month's statement of that log, made by the archive itself |
| `ledgers/` | the meter's ledger files: every evaluation line under every batch root |
| `tokens/<sha256>.jwt` | signed tokens, each under the SHA-256 of its bytes: a batch's, a close record's |
| `receipts/`, `statements/`, `closes/`, `other/` | receipts, statements for accounts payable, close records, anything else |
| `terms/<sha256>.json` | the terms, each under its hash |
| `keys/jwks.json` | the issuer's keys the tokens name, and in the manifest the day they were read and from where |
| `MANIFEST.json` | every file's SHA-256, the log's head, and `evidence_root` |
| `verify.py` | the verifier |

The same files give the same bytes on every machine (names in order, no compression, one date), so two parties who
build the archive from the same evidence hold the same file. No archive is written that its own verifier does not
pass.

Who keeps what:

| Holder | Keeps | Why |
| --- | --- | --- |
| the buyer | the archive, and its own ledger | it pays on this evidence |
| the supplier | the archive, and its own ledger | it is paid on this evidence, and must be able to show it |
| a third holder, if the two name one (an auditor, or an agent that holds money for both) | the archive | so that neither side's copy is the only other one |
| the chain | each batch's root and running hash | so that a ledger cannot be swapped for another afterwards |
| Knos | nothing that the others lack | it hosts no copy that anyone depends on |

`knos archive compare A B` says whether two holders hold the same evidence. It hashes both sides again and compares
one root; when they differ it names each file only one side holds, each file that differs, and how the two logs
stand to each other: one continues the other, or they part at a named line.

This is how public logs are cross-checked: a second party states which version it has seen ([C2SP,
tlog-cosignature](https://github.com/C2SP/C2SP/blob/tlog-cosignature/v1.0.0/tlog-cosignature.md)). Here the second
party is the other side of the contract, and its statement is the acknowledgement in the log.

### Completeness: numbers, gaps and corrections

A root cannot say that something was left out. A number can. Each sender numbers what it sends, from 0, per buyer, supplier and month, and the number travels in the event's `evidence`. The batch mode has always done this: a batch's `seq`.

`knos events gaps LOG` names every number below the highest that arrived that is not in the log. Trading systems find lost messages the same way: each message is numbered, and the receiver asks again for a number that is missing ([Cboe, FIX session protocol, message
recovery](https://www.cboe.com/document/tech-spec/content/technical-specifications/cboe-titanium-u.s.-equities-fix-specification/implementation-notes/common-session-level-issues/financial-information-exchange-protocol--session-protocol--message-recovery)).

A gap ends in one of two ways. The missing arrival is ingested. Or a correction record names the number, says that
nothing was sent under it and why, and a party acknowledges a head after it with a signed token. `knos events close
LOG --month YYYY-MM` refuses a month while a gap has neither.

- **Corrections are appended.** A correction names what it corrects (an event, or a missing number) and says what
  holds from now on. No line is rewritten: the log before the correction is a prefix of the log after it.
- **One deliverable id, ever.** An acceptance takes its id from its deliverable alone, so a deliverable accepted
  again in a later month is a repeat, counted once, and at another amount it is a conflict, refused. A second
  invoice line for it, in any month, is a `duplicate` in that month's statement and is never agreed. A second
  settlement is named by `knos events dupes` with both lines; it is not refused, because one deliverable can be
  paid in two parts.
- **The end of a run.** Numbers cut from the end leave a shorter run that is still a run. They are found only when
  the sender states its last number: `--last BUYER:SUPPLIER:YYYYMM.N`.

#### Counterpart acknowledgements and closure

A number finds what never arrived; it cannot show that both sides saw the same lines. Each party signs the month's last
line, its hash and the month's root with the Ed25519 key its terms name, and a month closes only with both signatures or
with a closure after the silence the terms allow (`src/knos/events.py`).

`knos archive make --ack FILE` keeps each signed file under `acks/<sha256>.json`, beside the terms under `terms/`.

The archive's `verify.py` checks each signature with nothing but Python, that the key is the one the archived terms
name, that every acknowledged line is still in the log, and names `missing-after-ack`, `changed-after-ack` and
`event-after-close`; a month not closed is a note marked `OPEN`, which `--strict` fails on. `knos archive policy` holds
an archive whose month is open.

### What survives if Knos disappears

`verify.py` is one file. It imports the Python standard library and nothing else, it does not import `knos`, and
it opens no connection. A holder unpacks the archive and runs `python verify.py`. The test runs it with
`python -I -S` in a directory that holds only the unpacked archive, after showing that `import knos` fails there.

| It checks again | How |
| --- | --- |
| every file | SHA-256 against the manifest; the evidence root from those hashes |
| the log | each line canonical, chained to the one before; each id the id of what the line says; a repeat counted once; no two claims under one id |
| acknowledgements and tokens | RS256 (RSA, PKCS#1 v1.5) and ES256 (ECDSA on P-256) signatures, in plain integer arithmetic, against the archived keys |
| what a token was signed for | a batch of an archived ledger (root, count, accepted count, value), a close record in the archive, or a head of the log |
| each month's statement of the log | made again from the log, compared byte for byte |
| each ledger | every evaluation id, every batch root in commitment formats 1 and 2, count, accepted count, value, batch numbering, the month's running hash |
| a statement for accounts payable | its own hash, and every total from its lines; each line of a statement made from the log is a line of the archived log |
| the terms | the bytes hash to the name |

What it does not check, and prints as a note:

- **That the archived keys are the issuer's.** It prints their SHA-256 and the day they were read. Compare that
  hash with the copy another holder kept, or with the issuer's own document while the issuer publishes it.
- **The chain.** It prints each month's running hash. Compare it with the meter's Ledger account, through any
  Solana node.
- **A batch with no token in the archive.** Its root is recomputed, and is the holder's word until a signed token
  for it is added. The note is marked `UNSIGNED`.
- **A missing number.** Named, and marked `INCOMPLETE` unless an acknowledged correction explains it.
- **A receipt.** Kept and checked by hash. Its referee's token is checked when that token is in the archive.
- **A meter statement** (`knos meter statement --json`): its counts, its fee and that its lines are in an archived
  ledger. The rule that picks one billed outcome per deliverable is not run again; `knos meter verify` runs it.
- **What nobody ever recorded.** If neither party's sender numbered it and neither kept it, nothing can show it.

`python verify.py --strict` fails on a note marked `INCOMPLETE` or `UNSIGNED`.

There is one verifier, in Python. A second one in another language does not exist.

### Retention

`knos archive policy RULES ARCHIVE...` reads a retention policy, the file `knos vault retain` already reads
([examples/private/retention.json](../../examples/private/retention.json)): keep a number of years of 365 days from
the day the archive was sealed, then delete, or remove the evidence and keep the hashes. It reports, for each
archive, `keep`, `held`, or what the policy makes due. It deletes nothing.

An archive past its years is `held`, with the reason, while any of these is true:

- a month in it is open: fewer than two parties have acknowledged a head that covers it;
- an invoice line in it is in dispute, or a deliverable's verdict is `disputed`;
- a number is missing without an acknowledged correction;
- a close record in it says `disputed`;
- it does not verify.

### Tests

`tests/test_archive.py` and `tests/test_events.py`:

| Statement | Test |
| --- | --- |
| the same evidence gives the same bytes | `test_the_same_evidence_is_the_same_bytes_and_holds_what_a_reader_needs` |
| the verifier is one file of the standard library | `test_the_verifier_is_one_file_of_the_standard_library_with_no_knos_and_no_network` |
| it verifies where Knos cannot be imported | `test_it_verifies_in_an_empty_directory_with_knos_unimportable` |
| it agrees with Knos on the log, both ledger formats and the statement | `test_the_standalone_checks_agree_with_knos_on_every_format` |
| a change is found even when the manifest is written again | `test_what_was_changed_is_found_even_when_the_manifest_was_written_again` |
| no archive is made of evidence that does not verify | `test_no_archive_is_made_of_evidence_that_does_not_verify` |
| two holders compare by root | `test_two_holders_compare_by_root_and_what_differs_is_named` |
| a policy holds what an open month or dispute needs | `test_a_retention_policy_reports_what_is_due_and_holds_what_an_open_month_or_dispute_needs` |
| a missing number is named | `test_a_number_a_sender_gave_that_never_arrived_is_named` |
| a gap closes a month only under an acknowledged correction | `test_a_gap_closes_a_month_only_under_a_correction_a_party_acknowledged` |
| one deliverable is counted once across periods | `test_one_deliverable_is_counted_once_across_periods` |
| the archive carries both parties' acknowledgements and its verifier checks them | `tests/test_events_period.py::test_the_archive_carries_the_acknowledgements_and_its_verifier_checks_them` |
| a month left open, and an event after its close, are named | `tests/test_events_period.py::test_the_archive_verifier_names_a_month_left_open_and_an_event_after_close` |
| lines cut after an acknowledgement are named | `tests/test_events_period.py::test_the_archive_verifier_names_lines_cut_after_an_acknowledgement` |

### What has not happened

No outside party holds an archive or has signed a month. Every month was signed in tests with test keys, except one month below:
a test period signed with Knos's own test keys. Every archive but one was made in tests, from test keys, or from this repository's
samples.

The one other is a test period: month 202610 of one account paired with itself, whose three
batches are anchored at the public knos_meter on devnet, with the six tokens GitHub signed for them. Its run is in
[`archive_verify.json`](../archive_verify.json) under `real`: 13 checks hold, 5 notes.

The month is closed by both acknowledgements its terms name (`knos events sign`, 8 October 2026), and both keys are Knos's own, so it
is one person's word on both sides. Among the notes is `INCOMPLETE` (the log of events it holds starts at number 1), so `--strict` fails
on it.

`python scripts/archive_verify.py --real ARCHIVE --source TEXT` records such a run; the archive is not in this repository, so later runs
and `--check` keep that part as written.

One more run is recorded, on sample data: `python scripts/archive_verify.py` makes an archive of the sample ledger
(`examples/meter/buyer.jsonl`) and the statement the site shows (`web/statement_sample.json`), unpacks it into an
empty folder and runs the `verify.py` inside it with `python -I -S`. What it printed is
[`archive_verify.json`](../archive_verify.json).

The samples carry no signed token, so the verifier checks their roots by hash only and says so in a note.
`--check` runs it again and fails when the record differs.
