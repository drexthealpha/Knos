<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# Finance: one record for whoever approves the bill

**In plain words.** This page is for the person who approves a bill. For each piece of work, it shows who asked for it, what was delivered, why it passed, and what was paid. All of it uses [test money](../WORDS.md#test-usdc), and nothing is owed until the buyer and the supplier agree that it is.

For a controller, and for the finance operator on the supplier's side. Everything here is on devnet.

The question this page answers for one deliverable: who authorised the work, under which budget, what was
delivered, why it was accepted, whether it was billed before, and what happens if it is reversed.

    knos audit show <order>                      # one deliverable, as the four records below
    knos audit export --owner <org> --from 2026-09-01 --to 2026-09-30 --format generic --refs refs.csv --out close.csv
    knos audit verify close.csv                  # every row's hash, the totals and the head
    knos audit owed --payee <login>              # the supplier's side

All four read the escrow's own log lines on Solana ([`src/knos/audit.py`](../../src/knos/audit.py),
[`src/knos/records.py`](../../src/knos/records.py)). No database is kept, and nothing is asked of GitHub.

**With no command line.** The approver's screen of the site ([CONSOLE.md](CONSOLE.md#the-approvers-screen),
[`web/approver.js`](../../web/approver.js)) opens the same statement and status files in a browser: one row per invoice
line from supplier to payment status, one queue of exceptions, the approval `knos statement approve` records, and
these exports as downloads. It adds one check the statement does not make, as advice only: a line that takes the
agreed sum past the purchase order limit the invoice file states is held out of the approval.

## 1. The four linked records

One deliverable is an order and a milestone: `order:funding transaction:milestone`. A work order has one
milestone, 0. A standing order pays once per pull request, so its milestone is the pull request. A bounty on an
issue has one.

| record | what it holds | where it comes from |
|---|---|---|
| **Authorisation** | buyer (the Balance's owner and the funder), supplier (each GitHub id paid, its wallet, its share), scope (repository id, issue, deliverable), budget (which Balance or wallet; its limits at funding), who approved and in which role | the funding's log line. The limits at funding are not in the log: the acceptance receipt of the paying transaction has them ([RECEIPT.md](RECEIPT.md)), and `knos audit show` rebuilds it. |
| **Acceptance** | artifact (the pull request, or the commit on a revert), policy (the terms' hash and version, paid on the merge or on tests), evaluator (which rule of the program accepted the signed run; with a receipt, each evaluator's owner, starter and whether either is the buyer's or the seller's), evidence (a link per transaction), verdict | the paying line, the terms the funding logged, and the receipt |
| **Commercial record** | deliverable, amount accepted, fee, currency, the buyer's own reference, billed before (yes or no), dispute, correction | the statement's rows; the reference and an open dispute come from the buyer's refs file |
| **Settlement status** | one of the states of section 2, the amounts behind it, and until when a hold lasts | the statement's rows; a payment by bank comes from the refs file |

**Who approved.** A comment by the Balance's owner or by one of its listed spenders funds an order at once,
within the Balance's limits ([CONTROLS.md](CONTROLS.md)). That is one person. The record says so:
`two_person` is false.

The two-person approval Knos has today is outside Knos: fund the order from a Squads multisig's vault
([`scripts/squads_fund.mjs`](../../scripts/squads_fund.mjs)). The vault signs only after the multisig's threshold of
members approved. `knos audit show` finds the multisig among the accounts of the funding transaction, checks
that the funding wallet is one of its vaults, and prints the threshold, the members and the members who
approved the proposal. A threshold of 1 is reported as not a two-person approval. If the proposal's account was
closed after it ran, who approved is no longer on chain, and the record says that.

**The buyer's reference.** The terms an order is paid under are hashed on chain and have no free-text field, so
a purchase order number is never put there. It goes in a side file of your own:

    order,ref,paid_outside,dispute
    <order address>,PO-4411 line 2,,
    <order>:<funding transaction>:<milestone>,PO-4412 line 1,2026-09-28 bank ref 77120,
    <order address>,PO-4413,,the second payee's share is contested

`order` is an order's address (every deliverable of it) or one deliverable. The file is your own statement, not
the chain's: it changes no row and no hash of the statement, and the other side does not see it unless you send it.

## 2. Settlement status

Five states of the money, and one correction. A record has exactly one.

| status | when |
|---|---|
| `paid on devnet (test money)` | the escrow sent the accepted amount to the supplier's wallet. If a part is held back in a review window, the record says how much and until when. |
| `payable` | accepted, and owed: the escrow holds it for a supplier who has named no wallet yet. The supplier names one (`knos claim <address>`), then anyone settles. |
| `held` | funded, and nothing is accepted yet. The escrow holds the price until the order's deadline. |
| `refunded` | nothing was accepted by the deadline (or the rest of a standing order was left over), and the money went back to the funder. |
| `paid outside Knos` | the buyer's refs file says it paid by bank and uses Knos for the count. The chain cannot confirm this. If the chain also shows a payment, the record says to check that it was not paid twice. |
| `reverted` | the correction: accepted, then reverted inside the review window. What the order still held went back to the funder; what was already paid stays paid, and the commercial record carries a credit for the part that went back. |

## 3. The statement, and how the other side recomputes it

`knos audit export --owner <org> --from <day> --to <day>` writes every line of the organisation's work orders
and of its bounties on issues: payments, released holdbacks, kill fees, refunds, reverts, and what is still open
or held at the end of the period. Each row carries the hash of the row before, and the file ends with the totals
and the **head**, the last row's hash.

The file is a function of the chain and the period. A supplier, an auditor or anyone else runs the same command
for the same owner and days and gets the same bytes. Two parties compare one hash, the head, and do not need to
send each other the file. `knos audit verify <file>` finds an edited, removed, added or reordered row. It cannot
find a file rewritten whole, hashes and all: that is what comparing the head against your own export is for.

Version 2 of the file (Knos 0.3.16, 5 Oct 2026) lists bounties beside work orders (`record` is `order` or `bounty`) and adds
`source`, `terms_version`, `paid_each` and `held_until`. Version 1 listed work orders only, so an organisation
that had only posted bounties got an empty file. A version 2 CSV starts with the line
`knos.audit-export,version,2`; the JSON has `version`. A version 1 file still verifies.

## 4. Files a finance system imports

`knos audit export ... --format netsuite|sap|coupa|quickbooks|generic` ([`src/knos/exports.py`](../../src/knos/exports.py)).
One line is one accepted deliverable for one supplier. Nothing accepted, no line. The same statement, refs file
and options give the same bytes.

Every line carries a bill number (`KNOS-` and 11 hex digits of a hash of the deliverable and the supplier: 16
characters), the UTC day of acceptance, the supplier as `gh:<GitHub id>`, the amount with two to six decimal
places (never rounded), and a memo with the settlement status, the statement's head and the receipt link (the
paying transaction, from which `knos receipt` rebuilds the acceptance receipt).

| format | what the product documents | what could not be confirmed there |
|---|---|---|
| `netsuite` | [Vendor Bill Import](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N427250.html), read 2026-10-06: External ID is the unique id of a record and is written on every line of it; it is mapped to Reference No.; the body fields Vendor and Date; on the Expenses sublist, Account, Amount and Memo; a new record needs at least one line. The currency is taken from the vendor record, so the file has no currency column. | The date format: the page names none, and M/D/YYYY is written (`--date-format` changes it). The body field Memo. Which fields an account's own form makes mandatory: [the page on required sublist fields](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N451547.html) names none. **Best effort, unverified** for those three. |
| `quickbooks` | [Import bills in QuickBooks Online](https://quickbooks.intuit.com/learn-support/en-global/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_ROW_en) read 2026-10-06 (the [Canadian edition's page](https://quickbooks.intuit.com/learn-support/en-ca/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_CA_en_CA) was the earlier source and was not read again that day): the mandatory columns Bill no., Supplier, Bill Date, Due Date, Account, Line Amount and Line Tax Code; every line of a bill repeats Bill no., Supplier and Bill Date. The date format is chosen at import, and the page's example is D/M/YYYY, which is what is written. The page recommends at most 100 bills a file. | The optional columns Line Description and Memo. The United States edition: its own page could not be read, so its column names (it says vendor where others say supplier) are not confirmed. **Best effort, unverified** for those. Line Tax Code is empty unless `--tax-code` is given. Due Date is the bill date: Knos knows no payment terms. |
| `coupa` | [Invoices Import](https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/coupa-core-flat-files-(csv)/flat-file-(csv)-import/invoices-import): the row types Invoice, Invoice Line and Invoice Charge; the first 24 columns of the Invoice row, in order; a date carries no time (read again 2026-10-07). | The Invoice Line row written here is not the page's: the page lists Supplier Part Number and Auxiliary Part Number between Description and Price, names the unit column Unit of Measure (this file writes UOM), puts some twenty columns between it and PO Number, and has PO Line Number and Match Reference, which this file lacks. Also not confirmed: the Invoice row's columns after the 24th, and the order of the date's parts. **The whole file is best effort, unverified.** |
| `sap` | [SAP note 3782347](https://userapps.support.sap.com/sap/support/knowledge/en/3782347) on the app Import Supplier Invoices (F3041): a spreadsheet template with one row per item, the invoice ID in the first column, and the header fields repeated on every row of an invoice. | Every column name, the date format and the field lengths. SAP publishes the template inside the app, not on a public page. **The whole file is best effort, unverified.** Copy its columns into the template your system gives you. |
| `generic` | Knos's own: one line per accepted deliverable with every field above in its own column, then the whole statement, row by row. | Nothing: it is specified here and in `exports.py`. |

**Every file here is a file export, not an integration.** It becomes an integration only after somebody imports it into
the product and reconciles the result, and nobody has: `exports.IMPORTED` is the list of formats that happened for,
and it is empty.

None of the four products' files has a place for a comment, so an unverified file does not say so inside itself.
The command says it on standard error each time it writes one, and this table says it.

Three things to know before importing:

- **Test money is written as USD.** An accounting system has no currency for test USDC. Every memo of a devnet
  payment starts with `TEST MONEY (devnet test USDC): not a payable`. Import into a sandbox company.
- **Vendors are GitHub ids.** The chain has ids, not names. Map `gh:<id>` to your vendor records in the
  import's mapping step, or create the vendors with that external id.
- **SAP's fields are short.** Its reference takes 16 characters and its item text 50, and a hash is 64. The SAP
  file carries the first 16 hex digits of the head and the start of the paying transaction. The full values are
  in the generic file, under the same bill number.

Options: `--account` (the expense or general-ledger account every line is booked to), `--entity` (SAP's company
code, Coupa's chart of accounts), `--tax-code`, `--date-format`.

**The generic file round-trips.** It carries the statement it was made from. `knos audit verify close.csv`
takes the statement back out, checks every hash, and prints the head: the same head the supplier gets from its
own export of the same period.

## 4a. The statement of one invoice, for accounts payable

`knos statement` ([`src/knos/statement.py`](../../src/knos/statement.py)) is the statement an approver attaches to a
supplier's invoice. It needs no chain and no wallet.

    knos shadow invoice.csv --out sept/                        # the invoice against GitHub's record; keeps evidence.json
    knos statement make sept/evidence.json --invoice INV-2026-09 --currency USD --prior aug/ap-statement.json
    knos statement approve sept/ap-statement.json --agreed --by "Dana Reyes" --role "finance controller"
    knos statement pay sept/ap-statement.json --line inv_... --method bank --ref "BACS 77120" --on 2026-10-02
    knos statement show sept/ap-statement.json
    knos statement export sept/ap-statement.json --format quickbooks
    knos statement verify sept/ap-statement.json

`make` also takes a closed month of the meter (the archive of `knos meter export --bundle`, section 5): one line per
deliverable the supplier's ledger accepted that month.

**Three forms, one content.** `ap-statement.json` is the statement. `ap-statement.csv` and `ap-statement.pdf` are
written from the same cells, in the same words, and both carry the JSON's SHA-256. The PDF is written by
[`src/knos/pdf.py`](../../src/knos/pdf.py) with no dependency: built-in Helvetica, ruled tables, as many pages as needed,
the statement's own day as its creation date, so the same statement gives the same bytes. A character outside
Windows-1252 prints as `?` in the PDF; the JSON and the CSV carry it.

**Each line** carries the four ids of [`src/knos/ids.py`](../../src/knos/ids.py) (the deliverable, its evaluations,
the invoice line, and a settlement once one is recorded), its amount, where its evidence is, and one state:

| state | means | why, in the file |
|---|---|---|
| policy met (written `agreed` in the file) | the evidence met the policy; nobody has accepted, authorised or paid it yet: those are the next three steps | |
| disputed | the evidence contradicts it | "a check failed when this change was merged: test", "the pull request is not merged", "the two ledgers give this evaluation different verdicts" |
| duplicate | the deliverable is billed already | "billed twice on this invoice: same pull request as line 1", "already billed: invoice INV-2026-09 line 1 agreed this deliverable on 2026-09-30" |
| insufficient evidence | nothing says either way | "the checks give no verdict: no check ran", "GitHub could not be read for this line: rate limit" |

**Already billed.** `--prior` takes earlier statements. A deliverable one of them agreed is a duplicate here, and the
new statement keeps that statement's hash and the line that billed it. A line that was disputed earlier and is
billed again is not a duplicate. In a shadow run the deliverable is the issue a pull request closes, or the pull
request when it closes none, so a second pull request for the same issue is caught and a second invoice for
unrelated work in the same repository is not.

**Approval.** `approve --agreed` records who authorised payment of the lines whose policy is met (policy satisfied is the first of four steps; parties accepted, payment authorised and settled are recorded apart), in which role and on which day. The other
lines stay open: no command here approves an exception. The role is written as stated; Knos has no accounts to check
it against (`knos budget who` shows who may spend a Balance on chain, which is a different authority).

**Payment status when paid outside Knos.** `pay` appends a settlement record with its own id, the method, the
payer's reference and the day. States: payable, paid outside Knos, held, refunded, devnet demonstration. It records
what the payer says. It moves no money and checks no bank. A line paid though not agreed is said so under Credited.

Approvals and payments go to `ap-statement.status.json`. The statement itself never changes after it is made; the
CSV and the PDF are written again and carry both hashes.

**What `show` answers:** what was authorised, billed, delivered and passed; what was already billed; who approved;
what is disputed, credited, paid and owed. A shadow run reads no order, so "authorised" says it is not known there.

**Made again years later.** The statement holds its own SHA-256, the SHA-256 of every piece of evidence, and the
evidence itself (or, with `--reference`, the hash of a file kept beside it). `verify` makes the statement again from
that evidence and prints `same`, or the first line that differs, for example
`differs: line 2: state is 'agreed' in the statement and 'disputed' from the evidence`. It asks no network and no
chain. For a closed month it checks GitHub's signatures on the close record with the keys in the archive. For a
shadow run there is no signature to check: GitHub does not sign its API's answers, so the evidence is what was read
on the day, and the statement says "not signed".

**The goods-received note.** Accounts payable pays a line when three documents agree: the purchase order, the
receipt of goods and the invoice. `knos statement grn` shows the three legs of one line side by side and says
`MATCH`, or each mismatch in words. This is the three-way match, for one deliverable:

    knos statement grn sept/ap-statement.json --line inv_... --receipt receipt.json --po PO-2026-0931
    knos statement grn sept/ap-statement.json --line inv_... --receipt receipt.json --po PO-2026-0931 --record

| leg | what it shows | read from |
|---|---|---|
| purchase order | the order's number (`--po`, the buyer's own, or the order's address), the hash of its terms, who approved the money, the price | the payment's acceptance receipt |
| receipt of goods | the note's reference, the verdict, the evaluator and who controls it, the assurance level, the evidence | the receipt; without one, the statement's line |
| invoice line | the line's id, reference, amount, state and payment | the statement and its status file |

The mismatches it names: no purchase order on record (a statement alone does not carry the order); no evaluation
on record; a receipt that nothing ties to the line; a receipt whose verdict is not accepted; an invoice line that
bills more than the order's price; a line that is disputed, duplicate or without enough evidence. It exits 1 on a
mismatch. It reads, and approves and moves nothing. `--record` appends the note to the status file.

**Assurance level on every line.** Each line says how much was verified, computed and never typed
([RECEIPT.md](RECEIPT.md), Version 5): the level of the receipt a recorded note was made from; without one,
`reported` for a line an evaluation stands behind, and `not evaluated` for a line with none. The statement's own
JSON does not change, so a statement made before this still verifies.

**Exports.** `export --format quickbooks|netsuite` writes one bill per agreed line, in the columns of the table
above, with the line's state, its payment status and its ids in the memo. A disputed or duplicate line, or one
without enough evidence, is never a bill. `--format generic` lists every line with its state.
Every export carries the three things a three-way match keys on. The generic file and the statement's CSV have a
column for each: `po_reference` (empty until a note is recorded), `grn_reference` and `assurance`. QuickBooks' and
NetSuite's import templates have no such columns, so there the same three are in the memo
(`PO ... | GRN ... | assurance ...`). Each remains a file export, not an integration.

**For your accounting system.** `export --to xero|quickbooks|netsuite|csv` writes the bill-import file that system
documents ([`src/knos/erp.py`](../../src/knos/erp.py)), and a held sheet beside it:

    knos statement export sept/ap-statement.json --to xero --account 400 --tax-code "Tax Exempt"
    # wrote sept/ap-statement.xero.csv: 1 bill ...; wrote sept/ap-statement.xero.held.csv: 4 held lines ...

- The payable file has one bill per line whose policy is met and that is not owed to the supplier. Its memo carries
  the line's four steps (policy satisfied, parties accepted, payment authorised, settled, each with who and when)
  and its assurance level, then the statement's hash and the line's ids. Xero's bill template has no memo column,
  so there they follow the line's description.
- The held sheet (`<file>.held.csv`) has every other line, with why: disputed; owed to the supplier (its policy is
  met and the buyer refused it, or nobody authorised it within 30 days); duplicate; without enough evidence. These
  lines never reach the payable file, in any format.
- `--date-format` changes the date (written with YYYY, MM, DD, M and D); `--account` and `--tax-code` fill the
  account and tax columns. Xero's account and tax columns take codes from your own organisation, so Knos leaves
  them empty unless given.

| `--to` | columns | read from | not confirmed |
|---|---|---|---|
| `xero` | ContactName, InvoiceNumber, Reference, InvoiceDate, DueDate, Description, Quantity, UnitAmount, AccountCode, TaxType, InventoryItemCode, Discount, Currency; date DD/MM/YYYY (US organisations: MM/DD/YYYY) | a [published guide](https://invoicedataextraction.com/blog/import-invoices-xero), read 2026-10-09: Xero's [own page](https://central.xero.com/s/article/Import-bills-and-credit-notes-US) draws its text by script and could not be read here | whether Xero's header marks required columns with asterisks; the whole file is best effort, unverified |
| `quickbooks` | Bill no., Supplier, Bill Date, Due Date, Account, Line Description, Line Amount, Line Tax Code, Memo; date D/M/YYYY, chosen at import | [QuickBooks Online, United States edition](https://quickbooks.intuit.com/learn-support/en-us/help-articles/importing-your-bills/00/261324), read 2026-10-09: the seven mandatory columns, at most 100 bills a file recommended | the optional columns Line Description and Memo |
| `netsuite` | External ID, Vendor, Date, Reference No., Memo, Expenses : Account, Expenses : Amount, Expenses : Memo; date M/D/YYYY | [NetSuite Vendor Bill Import](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N427250.html), read 2026-10-09 | the date format and the body Memo; Vendor is the supplier's name here, to be mapped to the vendor's id |
| `csv` | Knos's own: one column per step, plus assurance, payment and the ids | this page | |

Each is a file export, not an integration: nobody has imported one into the product yet. On the statement page,
**Download for your accounting system** writes the same two files in the browser ([`web/erp.js`](../../web/erp.js);
`tests/web/erp.mjs` holds the bytes equal to the Python's).

In a browser: `renderStatements` in [`web/statements.js`](../../web/statements.js) opens a statement file, checks its
hash, downloads the same CSV and the same export files (`tests/web/statement.mjs` holds the bytes equal to the
Python's), and prints the statement alone to paper or PDF.

## 4b. Close one invoice in under 30 seconds (timed by a script)

You can close one invoice on the site alone; a script, not a person, was timed. Open the Approve page (`#approve`). Then:

1. Press **Try the sample**, or drop your invoice and its statement on the page.
2. Type your name and your role. Press **Approve** (or Enter).
3. Press **Download accounting file**. Pick QuickBooks or NetSuite beside it first, if you need to.

The page then says "Approved and exported". The file holds one bill for each line you approved. A line the page held
back (over its purchase order, or over your limit) is not in it. With the keyboard alone, **Go to approval** takes you
past the table to your name.

How long it takes. A script did it on the sample statement, from opening the page to the file saved
([`tests/web/close30.mjs`](../../tests/web/close30.mjs); the figures are in [`perf.json`](../perf.json), under `close`):

| Screen | How | Clicks | Script | With a person's pace |
| --- | --- | --- | --- | --- |
| Slow phone, 360 px wide | mouse | 4 | 5.8 s | 16.1 s |
| Slow phone, 360 px wide | keyboard | 0 | 5.5 s | 15.1 s |
| Laptop, 1280 px wide | mouse | 4 | 1.1 s | 11.4 s |
| Laptop, 1280 px wide | keyboard | 0 | 1.0 s | 10.6 s |

The slow phone is the profile of `tests/web/android.mjs`: a processor 4 times slower and a slow mobile network. A
script types faster than you, so the last column adds 0.3 s a key (about 40 words a minute) and 1 s a click. No person
was timed. The test fails if a close takes more than 4 clicks, or more than 30 s on the slow phone.

## 5. Month-end close in one command

    knos audit export --owner acme --from 2026-09-01 --to 2026-09-30 --format generic --refs refs.csv --out acme-2026-09.csv

That file is the month: one line per accepted deliverable with its status, your reference, whether it was billed
before, any dispute and any credit, followed by the statement and its head. Then:

1. `knos audit verify acme-2026-09.csv` prints the head. Send the supplier the head, not the file.
2. The supplier runs the export for the same owner and days and compares its head with yours.
3. A line whose `billed_before` is 1 is a finding: the program pays a deliverable once, and `verify` fails on it.
4. Lines with status `reverted` carry the credit. Lines with `payable` are owed and wait for the supplier's wallet.
5. For the ledger, write the same month in your system's format (`--format netsuite`, and so on).

Name `--to`. A file with an end is the same whoever exports it and whenever. A month that is not over yet says
what was true when it was written.

## 6. The supplier's side

    knos audit owed --payee <login>

What is owed to a supplier and why it is not paid yet, one line each, with the transaction as evidence:

| reason | meaning |
|---|---|
| held for a wallet | accepted, and held until a date for a supplier who has named no wallet |
| in a review window until a date | accepted and partly paid; the rest is held back, and a revert inside the window sends it back to the funder |
| reverted | that part went back to the funder and is not owed |
| disputed | a refs file says so, and names the deliverable. An open dispute is not a line on chain; an arbiter's ruling is. |

It reads the chain's records only. It names no owner and reads no repository, so it works with no access to
anything of the buyer's, and it keeps working after the buyer takes that access away.

What a supplier cannot see without the buyer:

- the evidence of a private order: the repository, the issue, the names of the checks and the text of the terms.
  The chain has a hash only ([CONTROLS.md](CONTROLS.md), section 6).
- the run logs and the pull request of a private repository, once access is removed;
- the buyer's own reference for a line, which is in the buyer's refs file;
- a payment the buyer made outside Knos.

What stays with the supplier: every line of `owed`, the transactions it names, and the acceptance receipt of each
payment. `knos receipt mirror` keeps a copy that verifies from the issuer's signature with no chain.

**The supplier's finance lead, on the site.** The supplier page ([`web/supplier_finance.js`](../../web/supplier_finance.js))
takes the funding comment or the order's address, reads the order's own account from devnet with one call
(`getAccountInfo`), and shows four rows, with no wallet and no sign-in:

| Row | Read from the order account |
| --- | --- |
| Funded | the amount the payees receive (escrowed at funding; the fee was paid by the funder on top), with a link to the funding transaction when the comment names it |
| Acceptance window | until when a passing run is paid (`payUntil`), counting down; after it, what is unpaid returns to the funder |
| Appeal | `/knos appeal <reason>`, free; who decides: the order's arbiter, or the neutral judge running the agreed checks again |
| Payment date | the day the checks pass, at the latest the window's end; with a holdback, the part kept back and the day it is released (the end of the warranty, unless a failing run reverts it) |

Amounts carry thousands separators. "Try the sample" shows a made-up order of 5,000.00 test USDC. On devnet all of it
is test money.

## 6a. When the buyer goes quiet

A supplier does not need the buyer's cooperation to be paid for accepted work. This is the path that exists, from
the code, walked on the simulator by [`tests/test_supplier_completes.py`](../../tests/test_supplier_completes.py)
(a job on the second deployment's knos_pay test build):

1. **The buyer funds, and signs nothing after that.** The money is in the program's vault; the job records its
   deadline and where a refund would go.
2. **The buyer cannot take it back before the deadline.** A refund sent by the buyer before the deadline is
   refused by the program (error 83), on the first day and on the thirteenth of fourteen.
3. **A rejection is appealed, and the money stays.** `/knos appeal <reason>` by the pull request's author moves the
   verdict to disputed. It costs the supplier nothing, only the supplier can open it, and it gives the buyer no way
   to the money either. The neutral judge runs the funded suite itself; if it passes, the rejection is overturned.
4. **The supplier settles itself.** The proof is the forge's signature over the pinned workflow's run. The
   supplier's own wallet sends it and pays the transaction fee; no signature of the buyer is in the transaction.
   The program pays the wallet the proof names and takes the fee.
5. **After that there is nothing to refund,** and the same proof pays nothing twice.
6. **With no accepted work by the deadline the money goes back to the funder.** A proof sent after the deadline is
   refused. Anyone may send the refund, the supplier too; it lands in the funder's account whoever sends it, and a
   refund addressed elsewhere is refused (error 88).

What this does not give the supplier: the deadline is the supplier's clock too, so an appeal opened late can be
right and still pay nothing; an order funded with `neutral off` can be judged only from its own repository or its named
judge's; and where no evaluator answers, the default is the refund. [DISPUTES.md](DISPUTES.md) has the clocks, the cancel
notice of an order and who can do what at each state. This walk with a quiet buyer ran on the simulator only: it
was not exercised on the public program ids.

## 7. What does not exist

- **Single sign-on on the public site.** Knos has no accounts. Identity is GitHub's and a wallet's. The self-host bundle
  has single sign-on through any OpenID Connect provider, tested against a stand-in provider only ([SELFHOST.md](SELFHOST.md)).
- **An approver Knos can vouch for.** `knos statement approve` writes down a name and a role as stated. Nothing checks them.
- **A payment Knos can vouch for when it is made by bank.** `knos statement pay` records the payer's reference; no bank is asked.
- **An approval workflow inside Knos.** One comment funds an order. The only two-person approval is a multisig's
  vault as the funder, and that is the multisig's rule.
- **A party that answers by contract.** No named legal entity, no terms of service, no support agreement.
- **A connection to any finance system.** These are files. Nothing sends them, and nothing reads a reply.
- **A purchase order system.** The goods-received note reads the order from the payment's receipt and takes the
  buyer's own PO number as typed (`--po`). Nothing checks that number against a purchasing system.
- **A statement line above `reported` without a receipt.** A shadow run and a closed month record what was
  reported; a higher level needs the payment's receipt, and no receipt of a public payment is of version 5 yet.
- **An import any of the four products has accepted.** The files are written from the products' public pages.
  No file here has been loaded into NetSuite, SAP, Coupa or QuickBooks.
- **Names.** The statement carries GitHub's numeric ids.
- **Limits at funding without the receipt.** The log lines do not carry them; a receipt is rebuilt for work
  orders, not for bounties.
- **The first deployment's bounties.** The statement reads the second escrow. `knos receipts` lists both.
- **History beyond the newest 1000 transactions of the escrow.** For an owner whose orders go further back the
  export is refused, or with `--partial` written as a file that says it is partial and whose head is not one to
  compare.
- **Real money.** Devnet only.

The same shaping for a page is [`web/finance_data.js`](../../web/finance_data.js): the four records and the five
files as pure functions. `tests/web/finance.mjs` holds its bytes equal to the Python's.
