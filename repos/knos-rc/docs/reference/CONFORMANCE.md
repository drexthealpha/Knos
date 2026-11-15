# Conformance: Knos's formats, with vectors

Another team can implement or depend on these formats without asking Knos anything. The kit in
[`conformance/`](../../conformance/) holds test vectors with their expected results, and a runner that feeds them to any
implementation and compares:

    python conformance/run.py --impl "<the command that runs your implementation>"

The command is started once. Each case arrives on its standard input as one line of JSON
(`{"id": ..., "op": ..., "input": {...}}`) and is answered on standard output with one line: `{"id": ..., "output": ...}`,
or `{"id": ..., "refused": true}` for an input the format does not allow, or `{"id": ..., "unsupported": true}` for an
operation the implementation does not do. The runner needs Python 3.10 and nothing of Knos's. `--require-all` makes an
unsupported case a failure; `--format terms` runs one format.

Kit version 4 has 370 cases. Version 2 added the receipt4 and ids rows, version 3 the ledger2 row, version 4 the receipt5 row; none changed a
vector of the version before:

| format | versions | cases | what it fixes |
|---|---|---|---|
| receipt | 1, 2, 3 | 59 | the acceptance receipt: which receipts are valid, and the digest of each ([RECEIPT.md](RECEIPT.md)) |
| terms | 1 | 37 | the terms of a job or an order: their canonical bytes and the hash the tokens carry |
| ledger | 1 | 31 | the meter's evaluation id, deliverable id, batch root and running hash |
| audiences | 1 | 36 | the text a signed token must carry for each instruction that takes one |
| statement | 1 | 8 | the meter's monthly statement and the hash both parties compare |
| receipt4 | 4 | 60 | the acceptance receipt of version 4: four verdicts, the four ids, what the evidence does not show, and which receipts authorise payment ([RECEIPT.md](RECEIPT.md), [`receipt/vectors.v4.json`](../receipt/vectors.v4.json)) |
| receipt5 | 5 | 40 | the acceptance receipt of version 5: the assurance level a reader computes from the receipt's evidence (reported, rerun, agreed; attested is refused), who stays trusted, and the control relationships the terms declare ([RECEIPT.md](RECEIPT.md), [`receipt/vectors.v5.json`](../receipt/vectors.v5.json)) |
| ids | 1 | 57 | the ids of a deliverable, an evaluation, an invoice line and a settlement, the four verdicts, and the rule that bills a deliverable once ([METER.md](METER.md)) |
| ledger2 | 2 | 42 | the meter's batch commitment, format 2: an event's canonical bytes, its leaf, a batch's root, an inclusion proof, and the pair of batches that differ only in which evaluation was accepted ([METER.md](METER.md)) |

The receipt's vectors are the ones [`docs/receipt/vectors.json`](../receipt/vectors.json) already held; the kit reads that
file and keeps no copy. Nobody outside Knos has run the kit: the two implementations that pass it are Knos's own.

## The formats

**Receipt** (`receipt.digest`, `receipt.check`, from version 4 `receipt.verdict`: the verdict of a valid receipt and whether it
authorises payment, and for version 5 `receipt.assurance`: the level, one word). [RECEIPT.md](RECEIPT.md) and the five JSON Schemas beside the vectors
say what a receipt is. The digest is sha256 of the receipt as JSON with its keys sorted, no white space, in UTF-8 with
nothing outside ASCII escaped. `receipt.check` answers `true` for a valid receipt and refuses an invalid one; some rules
are beyond what a schema can say (shares that add up, hashes that must agree), and the invalid vectors cover those.

**Terms** (`terms.hash`, `terms.canonical`). The terms are a JSON object with exactly `accept`, `checks`, `deny`,
`mode`, `paths`, `reserve` and `v` (which is 1), and optionally `image`, `policy`, `vendor`. Their canonical bytes are
that object as JSON with keys sorted, no white space, and every character outside printable ASCII written as a
`\uXXXX` escape in lower-case hex (a character outside the basic plane as its two surrogates); at most 600 bytes. In
canonical form `deny` and `paths` are in ascending order with no glob twice, and `checks` are ordered by name and then
by app, none twice. The terms hash is sha256 of those bytes, in lower-case hex: it is what the fund and pay audiences
carry and what the program stores. `terms.hash` takes terms that are already canonical; `terms.canonical` takes any
object, puts it in canonical form or refuses it. Whole numbers are exact: `vendor` may be above 2^53, which a language
whose only number is a double cannot hold without care.

**Ledger** (`ledger.eval_id`, `ledger.deliverable_id`, `ledger.batch_root`, `ledger.batch_root_any`,
`ledger.check_proof`, `ledger.chain_hash`). An evaluation's id is sha256(work order, 32 bytes || artifact, its 40
characters as text || policy, 32 bytes || milestone as u32 little-endian). A deliverable's id is sha256(work order ||
milestone as u32 little-endian). A batch's root is the Merkle tree of RFC 6962, section 2.1, over the ids in ascending
order, each once: a leaf is sha256(0x00 || id), a node sha256(0x01 || left || right), the split at the largest power of
two below the number of leaves, and no leaves give sha256 of nothing. A batch's corrections follow the ids as leaves
sha256(0x02 || key), in ascending order of key. `ledger.batch_root` takes ids already in order;
`ledger.batch_root_any` takes them in any order, with repeats and with corrections. `ledger.check_proof` checks an
inclusion path against a root. A ledger's running hash after a batch is sha256(hash before || root || seq || count ||
accepted || value), the four numbers as u64 little-endian, starting from 32 zero bytes.

**Ledger, format 2** (`ledger2.event_bytes`, `ledger2.leaf`, `ledger2.root`, `ledger2.check_proof`). Format 1's root
binds the set of evaluation ids, the count, the accepted count and the value; not which evaluation was accepted.
Format 2's leaf is the hash of the whole event. An event is eighteen texts, in this order: `deliverable_id`,
`evaluation_id`, `invoice_line_id`, `settlement_id`, `verdict`, `amount`, `currency`, `buyer`, `seller`, `order`,
`milestone`, `policy`, `artifact`, `evidence`, `evaluator`, `run`, `month`, `seq`. A whole number is written in decimal
with no leading zero, the month as six digits, a field the line does not state as the empty text. Its bytes are
`knos.event`, a zero byte, the byte 0x02 (the format), the byte 0x12 (the number of fields), then each text as its
length in bytes (u32 big-endian) and its UTF-8 bytes. An event whose verdict is not one of the four words, whose
numbers are written another way, or whose deliverable or evaluation id is not the id of its own order, milestone,
artifact, policy, evaluator and run is refused. A leaf is sha256(`knos.leaf.2` 0x00 || bytes), a node
sha256(`knos.node.2` 0x00 || left || right), a correction's leaf sha256(`knos.fix.2` 0x00 || key), and the root
sha256(`knos.root.2` 0x00 || the number of leaves as u32 big-endian || the top of the tree). The leaves are the events
in ascending order of their evaluation id (`ledger.eval_id`), then the corrections' keys in ascending order; an
evaluation given twice is refused. The tree splits at the largest power of two below the number of leaves, so a last
leaf with no sibling is carried up as it is and is never hashed with a copy of itself. The format and the number of
leaves are inside the root, and every tag differs from format 1's one-byte prefixes, so a root or a proof of one format
never checks as the other; the vectors include both directions and the pair that swaps which of two equal-priced
evaluations was accepted. The root goes in the same place of the same audience: the program reads it as 32 bytes.

**Audiences** (`audience.knos2_fund`, `audience.knos2_pay`, `audience.knos2_bind`, `audience.knos3_fund`,
`audience.knos3_pay`, `audience.knos3_rule`, `audience.knos3_bind`, `audience.knos3_take`, `audience.knos3_cancel`,
`audience.knos3_revert`, `audience.knos3_auto`, `audience.knosm_eval`, `audience.knosm_batch`,
`audience.knos_oidc_key`, `audience.gate`, `audience.parse_knosm_batch`). A program acts on a signed token only when
the token's audience is, character for character, the text the instruction's own facts give. Each vector is those
facts and that text: parts joined by colons, addresses as base58, hashes as lower-case hex, numbers in decimal with no
leading zero, an absent wallet as a hyphen. `audience.parse_knosm_batch` reads a batch audience back and refuses what
`knos_meter` refuses (a leading zero, a root in capitals, a number of 2^64, a part too many).

**Statement** (`statement.text`, `statement.hash`). A statement is lines of `name,value`, the first
`knos meter statement,1`. The hash both parties compare is sha256 of the bytes above the first line that starts
`sha256,`; the lines below it are one side's own record and are not hashed. `statement.hash` answers the hash it
computes, the hash the statement states, and whether they agree; `statement.text` writes the statement of one month of
a ledger file.

## The promise

It is narrow on purpose.

- **What is versioned.** The receipt says its version in `version`, the terms in `v`, the statement in its first line.
  An audience says it in its first part (`knos2`, `knos3`, `knosm`, `knos-oidc`, `gate`). The ledger's ids and tree
  have no version of their own: they are version 1 for as long as an audience that starts `knosm` carries them.
- **A version's vectors never change.** `conformance/manifest.json` names the sha256 of each version's vectors, the
  runner refuses to run against vectors that differ, and `tests/test_conformance.py` holds the same hashes a second
  time. Vectors may be added for a new version; the ones a published version has stay as they are. If a vector is
  found to be wrong, it is not edited: the version is withdrawn here in words and a new one takes its place.
- **A breaking change is a new version number.** A receipt, terms or a statement that an existing reader would
  misread gets the next number, and an audience whose meaning changes gets a new first part, as `knos3` followed
  `knos2`. The change is announced in [CHANGELOG.md](../../CHANGELOG.md) under the release that makes it and in the table
  above, with its vectors.
- **The old verifier keeps reading old receipts.** `knos` reads receipt versions 1 to 5 today, and a release that
  adds a version keeps reading the earlier ones. A receipt someone already holds does not stop verifying because Knos
  moved on.

## What is not promised

- **Program instruction layouts.** The order of an instruction's accounts, the bytes of its data, the sizes and
  fields of the accounts the programs keep, and their error numbers can change with any upgrade until an outside review
  of the programs has been done. None has. The 48 option bytes inside a `knos3:fund` audience are such a layout: the
  vectors carry them as given and say nothing about what each byte means.
- **Anything about devnet.** Addresses, balances and what is deployed there are test state.
- **The words of the command line and of error messages.** A refusal is promised; its wording is not.
- **Completeness.** The vectors are examples of each rule, not a proof that an implementation that passes them is
  right everywhere. Where this page and the code in `src/knos` differ, that is a defect in one of them: report it.

## Knos's own two implementations

`tests/test_conformance.py` runs both on every change.

| implementation | passed | not implemented | failed |
|---|---|---|---|
| Python (`conformance/impl/knos_python.py`, the functions the rest of Knos uses) | 370 | 0 | 0 |
| JavaScript (`conformance/impl/knos_js.mjs`, the client in `sdk/settle`) | 244 | 126 | 0 |

Of the JavaScript client's 244, 101 are answered by functions `sdk/settle` exports and 143 by a few lines in the adapter
written from this page and from the description in each vector file, for operations the client has no function for:
`receipt.digest`, `ledger.deliverable_id`, `statement.hash`, and the nine of the ids format (`ids.deliverable`,
`ids.evaluation`, `ids.invoice_line`, `ids.settlement`, `ids.kind_of`, `ids.expect`, `ids.order_scope`, `ids.verdict`,
`ids.billed_once`), and the four of ledger format 2 (`ledger2.event_bytes`, `ledger2.leaf`, `ledger2.root`,
`ledger2.check_proof`). They show that the descriptions are enough to write from; they are not a claim about the client.
The 126 it does not do are four operations. Before receipt version 5 they were three operations and 93 cases, and
the client passed 237 (244 now). Each is a difference between Knos's own two implementations that a user of the client
should know:

- `receipt.check` (99 cases): the client does not check a receipt's rules.
- `receipt.verdict` (19 cases): so it does not say a receipt's verdict, or whether it authorises payment.
- `receipt.assurance` (7 cases): nor the assurance level of a version 5 receipt, which is computed by the same rules.
- `statement.text` (1 case): the client has no function that writes a statement's text.
