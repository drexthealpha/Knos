# Finance: one record for whoever approves the bill

For a controller, and for the finance operator on the supplier's side. Everything here is on devnet: the money is
test USDC, and nothing is a payable until a buyer and a supplier agree off chain that it is.

The question this page answers for one deliverable: who authorised the work, under which budget, what was
delivered, why it was accepted, whether it was billed before, and what happens if it is reversed.

    knos audit show <order>                      # one deliverable, as the four records below
    knos audit export --owner <org> --from 2026-09-01 --to 2026-09-30 --format generic --refs refs.csv --out close.csv
    knos audit verify close.csv                  # every row's hash, the totals and the head
    knos audit owed --payee <login>              # the supplier's side

All four read the escrow's own log lines on Solana ([`src/knos/audit.py`](../src/knos/audit.py),
[`src/knos/records.py`](../src/knos/records.py)). No database is kept, and nothing is asked of GitHub.

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
([`scripts/squads_fund.mjs`](../scripts/squads_fund.mjs)). The vault signs only after the multisig's threshold of
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

Version 2 of the file (0.3.16) lists bounties beside work orders (`record` is `order` or `bounty`) and adds
`source`, `terms_version`, `paid_each` and `held_until`. Version 1 listed work orders only, so an organisation
that had only posted bounties got an empty file. A version 2 CSV starts with the line
`knos.audit-export,version,2`; the JSON has `version`. A version 1 file still verifies.

## 4. Files a finance system imports

`knos audit export ... --format netsuite|sap|coupa|quickbooks|generic` ([`src/knos/exports.py`](../src/knos/exports.py)).
One line is one accepted deliverable for one supplier. Nothing accepted, no line. The same statement, refs file
and options give the same bytes.

Every line carries a bill number (`KNOS-` and 11 hex digits of a hash of the deliverable and the supplier: 16
characters), the UTC day of acceptance, the supplier as `gh:<GitHub id>`, the amount with two to six decimal
places (never rounded), and a memo with the settlement status, the statement's head and the receipt link (the
paying transaction, from which `knos receipt` rebuilds the acceptance receipt).

| format | what the product documents | what could not be confirmed there |
|---|---|---|
| `netsuite` | [Vendor Bill Import](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N427250.html): the fields External ID, Vendor, Date, Reference No. and, on the Expenses sublist, Account, Amount and Memo. External ID groups the lines of one bill. | The date format: the page names none, and M/D/YYYY is written (`--date-format` changes it). The body field Memo. **Best effort, unverified** for those two. |
| `quickbooks` | [Import bills in QuickBooks Online](https://quickbooks.intuit.com/learn-support/en-ca/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_CA_en_CA): the mandatory columns Bill no., Supplier, Bill Date, Due Date, Account, Line Amount and Line Tax Code. The date format is chosen at import, and the page's example is D/M/YYYY, which is what is written. The page recommends at most 100 bills a file. | The optional columns Line Description and Memo. **Best effort, unverified** for those two. Line Tax Code is empty unless `--tax-code` is given. Due Date is the bill date: Knos knows no payment terms. |
| `coupa` | [Invoices Import](https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/coupa-core-flat-files-(csv)/flat-file-(csv)-import/invoices-import): the row types Invoice, Invoice Line and Invoice Charge; the first 24 columns of the Invoice row, in order; a date carries no time. | The columns of the Invoice Line row, the Invoice row's columns after the 24th, and the order of the date's parts. **The whole file is best effort, unverified.** |
| `sap` | [SAP note 3782347](https://userapps.support.sap.com/sap/support/knowledge/en/3782347) on the app Import Supplier Invoices (F3041): a spreadsheet template with one row per item, the invoice ID in the first column, and the header fields repeated on every row of an invoice. | Every column name, the date format and the field lengths. SAP publishes the template inside the app, not on a public page. **The whole file is best effort, unverified.** Copy its columns into the template your system gives you. |
| `generic` | Knos's own: one line per accepted deliverable with every field above in its own column, then the whole statement, row by row. | Nothing: it is specified here and in `exports.py`. |

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

## 7. What does not exist

- **Single sign-on.** Knos has no accounts. Identity is GitHub's and a wallet's.
- **An approval workflow inside Knos.** One comment funds an order. The only two-person approval is a multisig's
  vault as the funder, and that is the multisig's rule.
- **A party that answers by contract.** No named legal entity, no terms of service, no support agreement.
- **A connection to any finance system.** These are files. Nothing sends them, and nothing reads a reply.
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

The same shaping for a page is [`web/finance_data.js`](../web/finance_data.js): the four records and the five
files as pure functions. `tests/web/finance.mjs` holds its bytes equal to the Python's.
