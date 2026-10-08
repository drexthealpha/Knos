# Retention: what a root proves, who keeps what, and what is left if Knos disappears

A batch's Merkle root, anchored on chain, proves one thing: a line you hold is among the lines that were put under
that root, and has not changed since. It is a commitment. It is not a copy and it is not a count of what should
have been there.

| A root proves | A root does not prove |
| --- | --- |
| a line you hold was committed to, byte for byte | that anyone still holds the lines (availability) |
| the count, the accepted count and the value signed with it | that every evaluation was supplied (completeness) |
| nothing under it was changed afterwards | that the same deliverable is not also under another root, in another month |

Each right-hand cell is answered off chain, by something a second party can check without Knos. This page says by
what, and names the test behind each statement.

## Availability: every party keeps the archive

`knos archive make OUT.zip --events LOG --ledger FILE [--statement FILE] [--token FILE] [--receipt FILE] [--terms
FILE] [--close FILE] --keys JWKS --keys-read YYYY-MM-DD` writes one file:

| In the archive | What it is |
| --- | --- |
| `events/log.jsonl` | the log of events ([EVENTS.md](EVENTS.md)), with the acknowledgements signed into it |
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
| a third holder, if the two name one (an auditor, an escrow agent) | the archive | so that neither side's copy is the only other one |
| the chain | each batch's root and running hash | so that a ledger cannot be swapped for another afterwards |
| Knos | nothing that the others lack | it hosts no copy that anyone depends on |

`knos archive compare A B` says whether two holders hold the same evidence. It hashes both sides again and compares
one root; when they differ it names each file only one side holds, each file that differs, and how the two logs
stand to each other: one continues the other, or they part at a named line. This is the idea a transparency log's
witness serves: a second party states which head it has seen
([C2SP, tlog-cosignature](https://github.com/C2SP/C2SP/blob/tlog-cosignature/v1.0.0/tlog-cosignature.md)). Here
the second party is the other side of the contract, and its statement is the acknowledgement in the log.

## Completeness: numbers, gaps and corrections

A root cannot say that something was left out. A number can. Each sender numbers what it sends, from 0, per buyer,
supplier and month, and the number travels in the event's `evidence`. The batch mode has always done this: a
batch's `seq`. `knos events gaps LOG` names every number below the highest that arrived that is not in the log.
This is how a message session finds a lost message: the receiver compares each number with the one it expects and
asks again for what is missing
([Cboe, FIX session protocol, message recovery](https://www.cboe.com/document/tech-spec/content/technical-specifications/cboe-titanium-u.s.-equities-fix-specification/implementation-notes/common-session-level-issues/financial-information-exchange-protocol--session-protocol--message-recovery)).

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

## What survives if Knos disappears

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
- **A receipt.** Kept and checked by hash. Its judge's token is checked when that token is in the archive.
- **A meter statement** (`knos meter statement --json`): its counts, its fee and that its lines are in an archived
  ledger. The rule that picks one billed outcome per deliverable is not run again; `knos meter verify` runs it.
- **What nobody ever recorded.** If neither party's sender numbered it and neither kept it, nothing can show it.

`python verify.py --strict` fails on a note marked `INCOMPLETE` or `UNSIGNED`.

There is one verifier, in Python. A second one in another language does not exist.

## Retention

`knos archive policy RULES ARCHIVE...` reads a retention policy, the file `knos vault retain` already reads
([examples/private/retention.json](../examples/private/retention.json)): keep a number of years of 365 days from
the day the archive was sealed, then delete, or remove the evidence and keep the hashes. It reports, for each
archive, `keep`, `held`, or what the policy makes due. It deletes nothing.

An archive past its years is `held`, with the reason, while any of these is true:

- a month in it is open: fewer than two parties have acknowledged a head that covers it;
- an invoice line in it is in dispute, or a deliverable's verdict is `disputed`;
- a number is missing without an acknowledged correction;
- a close record in it says `disputed`;
- it does not verify.

## Tests

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

## What has not happened

No outside party holds an archive. Every archive but one was made in tests, from test keys, or from this
repository's samples. The one other is of a real period: month 202610 of the pair 142920951/142920951 (the founder's
own account on both sides), whose three batches are anchored at the public knos_meter on devnet, with the six
tokens GitHub signed for them. Its run is in [`archive_verify.json`](archive_verify.json) under `real`: 11 checks
hold, 6 notes, among them `INCOMPLETE` (the log of events it holds starts at number 1) and `UNSIGNED` (nobody
else acknowledged the log), so `--strict` fails on it. `python scripts/archive_verify.py --real ARCHIVE --source
TEXT` records such a run; the archive is not in this repository, so later runs and `--check` keep that part as
written.

One run is recorded: `python scripts/archive_verify.py` makes an archive of the sample ledger
(`examples/meter/buyer.jsonl`) and the statement the site shows (`web/statement_sample.json`), unpacks it into an
empty folder and runs the `verify.py` inside it with `python -I -S`. What it printed is
[`archive_verify.json`](archive_verify.json). The samples carry no signed token, so the verifier checks their
roots by hash only and says so in a note. `--check` runs it again and fails when the record differs.
