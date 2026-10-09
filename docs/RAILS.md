# We pay by bank

A buyer who pays suppliers by bank transfer and books invoices in an accounting system keeps doing both. Knos adds the
part before the payment: which invoice lines the evidence supports. This page is the route from evidence to a payment
instruction for the buyer's own bank, and back to a statement that says what was paid.

Nothing on this route moves money. Knos writes a file; the payer uploads it to their bank. **No bank has taken a file
this code wrote, and no accounting system has imported one.** Try each file in the bank's or the product's test
channel first.

## The route

| Step | Who | Command | What comes out |
| --- | --- | --- | --- |
| 1. Evidence | buyer or supplier | `knos shadow invoice.csv --out run/` (or a closed month, or a log of events) | `evidence.json`: the invoice and what the forge recorded about each line |
| 2. Statement | either | `knos statement make run/evidence.json --invoice INV-1 --currency USD` | `ap-statement.json`, `.csv`, `.pdf`: each line policy met, disputed, duplicate or without enough evidence, and its four steps: policy satisfied, parties accepted, payment authorised, settled |
| 3. Approval | the approver | `knos statement approve ap-statement.json --agreed --by NAME --role ROLE` | payment authorised for the lines whose policy is met, in `ap-statement.status.json`; every exception stays open |
| 4. Instruction file | the payer | `knos statement pay ap-statement.json --rail bank --payer-name N --payer-account IBAN --payees payees.csv` | `ap-statement.pain001.xml`, and a record of it in the status file |
| 5. Status | the payer | `knos statement status ap-statement.json --from bank-answer.xml` | each line paid, payable again with the bank's reason, or held as unknown when the answer is not clear |

`payees.csv` has one row a supplier: `supplier,name,account,bic`. The supplier is the statement's own word for it. The
account is an IBAN (its check digits are verified) or another account number of up to 34 letters and digits.

The same file can be made in the browser with no command line: `web/rails.js` exports `pain001(statement, payer,
status)` and a small view, `renderRails`. Both write the bytes the command writes
([`tests/data/rails/vectors.json`](../tests/data/rails/vectors.json) holds three cases; `tests/web/rails.mjs` compares).

`--rail usdc` is the path that already existed: it records a devnet payment of one line (`--line`, with the
transaction as `--ref`). Test USDC is never written into a bank file: a statement whose currency is not a three-letter
code is refused on the bank rail.

## What is in the instruction file

One ISO 20022 customer credit transfer initiation, message `pain.001.001.09`, with one payment block and one transfer
per supplier.

| In the file | What it is |
| --- | --- |
| Which lines | Only lines whose policy is met and whose payment is authorised, still payable, and in no earlier instruction file that the bank has not returned. A disputed or duplicate line, or one without enough evidence, is never in it. |
| `EndToEndId` | The settlement id (`stl_` and 24 hex characters, 28 characters; the field takes 35). It is made from the statement's hash, the supplier and the invoice lines the transfer pays, so the bank's statement, the supplier's and the Knos statement name one payment by one id. |
| `InstdAmt` | The sum of the supplier's lines, in whole cents, in the statement's currency. |
| `RmtInf/Ustrd` | First `KNOS <the statement's sha256> INV <invoice number>`, then the invoice line ids, four to a line. Each is at most 140 characters. |
| `MsgId` | `KNOS` and 28 hex characters of the statement's hash and the transfers: the same statement, status and payer give the same file. |
| Names | Cut to the letters, digits and `/ - ? : ( ) . , ' +` that every profile of the message accepts; any other character becomes a full stop. |

The status file records the instruction: the message id, the file's SHA-256, and which lines each transfer pays. That
record is why a line is never instructed twice and why the bank's answer finds its lines.

## What was checked, and what was not

Checked here, by `knos.rails.check`, on every file before it is written, and in `tests/test_statement_rails.py`:

- the namespace `urn:iso:std:iso:20022:tech:xsd:pain.001.001.09`;
- the order and presence of every element the file uses, against the element order of the message definition:
  `GrpHdr` (`MsgId`, `CreDtTm`, `NbOfTxs`, `CtrlSum`, `InitgPty`), `PmtInf` (`PmtInfId`, `PmtMtd`, `NbOfTxs`,
  `CtrlSum`, `ReqdExctnDt/Dt`, `Dbtr`, `DbtrAcct`, `DbtrAgt`, `CdtTrfTxInf`), and each transfer (`PmtId/EndToEndId`,
  `Amt/InstdAmt`, `CdtrAgt`, `Cdtr`, `CdtrAcct`, `RmtInf/Ustrd`);
- lengths and patterns: ids of 1 to 35 characters, names and remittance lines of 1 to 140, the IBAN and BIC patterns,
  the currency as three capital letters, the payment method `TRF`;
- that both transaction counts are the number of transfers, both control sums are their total, no two transfers share
  an end-to-end id, and every IBAN's check digits are its own;
- that the file is well-formed XML, by `xmllint` too where it is installed.

The element order, multiplicities, lengths and patterns were read on 2026-10-07 from two published descriptions of
the message: Payments Canada's
[CustomerCreditTransferInitiationV09 usage guideline](https://www.payments.ca/sites/default/files/CustomerCreditTransferInitiationV09%28pain.001.001.09%29.pdf)
(group header, payment block, the start of the transfer, the amount, account and agent types) and Nordea's
[message implementation guide for pain.001.001.09](https://www.nordea.com/en/doc/nordea-message-implementation-guide-cap-pain.001.001.09.pdf)
(the namespace, the transfer from the creditor's agent to the remittance, `Ustrd` as 140 characters).

Not checked:

- **The official schema file.** It is not in this repository and this machine could not fetch it, so the file was not
  run through a schema validator. The checker is written by hand from the two documents above and covers only the
  elements this code writes.
- **Any bank's own rules.** Banks accept a narrower message than the definition. Known differences: many accept one
  remittance line, not several (Nordea's guide processes one line of 140 characters for international payments); some
  require a BIC or a clearing code for the creditor's bank, a charge bearer, a postal address or a payment type. A
  payer adds what their bank asks for.
- **A bank.** No file was uploaded to one.

## The bank's answer

`knos statement status` reads either of two files.

A customer payment status report (`pain.002`, any version: it is read by element name). For each `TxInfAndSts` it
takes `OrgnlEndToEndId`, `TxSts`, the reason (`StsRsnInf`), the bank's reference (`AcctSvcrRef`) and the day. A report
that gives one status for the whole batch or file applies it to every transfer of that file. The element names were
read on 2026-10-07 from Payments Canada's
[CustomerPaymentStatusReportV10 usage guideline](https://www.payments.ca/sites/default/files/CustomerPaymentStatusReportV10%28pain.002.001.10%29.pdf).

Or a CSV with the header `end_to_end_id,status,reference,date,reason`, for a bank that sends no report: the payer
types what their bank statement shows.

| Status | What Knos records |
| --- | --- |
| `ACSC`, `ACCC`, or `paid` | each line of the transfer is paid outside Knos; its settlement id is the end-to-end id |
| `RJCT`, `CANC`, or `failed` | each line is payable again, with the bank's code and reason; the next instruction file names it under a new end-to-end id |
| `ACTC`, `ACCP`, `ACSP`, `ACWC`, `ACWP`, `ACFC`, `RCVD`, `PART`, `PATC`, `PDNG`, or `pending` | nothing: the transfer is still with the bank |
| `timeout`, `no answer`, `unknown`, `error`, or a code not in this table | each line is held as **unknown**: the money may have left. No new instruction file names the line until a later answer says paid or returned |

`ACSC` (settlement complete) and `RJCT` (rejected) are read as one bank's developer pages describe them
([Goldman Sachs Transaction Banking, payment status](https://developer.gs.com/docs/services/transaction-banking/best-practices-iso-paystatus/),
read 2026-10-07). That page says `ACSP` can be the last status a bank sends when no settlement confirmation arrives;
Knos keeps such a transfer pending, and the payer records it as paid with a CSV row once their statement shows it. The other
codes are sorted by their names in the ISO 20022 status code list (`ACCC`: settled on the creditor's account), which
was not read from a primary page here.

Reading the same answer twice changes nothing. A transfer no instruction file of this statement names is said and
skipped.

The status code list was checked on 2026-10-09 against
[Token.io's table of ISO 20022 payment status codes](https://docs.token.io/products/tpp/sip/sip-v2/iso-20022), which
also lists `PATC` (partially accepted, technically correct) and says the final status is not standardised across banks.

### An answer that is not clear is never a no

A payment adapter that retries after a timeout can pay twice. So Knos never treats an unclear answer as a rejection:

- An unclear answer holds each line of the transfer as unknown. The statement, its CSV and PDF, and the site show the
  line held, with "the bank's answer is not clear" and the code. `knos.rails.unknown` lists such lines.
- Only a later status file resolves it. Paid: the line is paid. Returned: the line is payable again, and the next file
  names it under a new end-to-end id. An unclear answer after a return holds the line again: the first transfer may
  have left after all.
- One end-to-end id, one instruction. `knos.rails.instruct` refuses a file that would reuse an id or a message id an
  earlier file of the statement used, whatever else the status file says.
- A payment reported for a line already paid under another end-to-end id is said as PAID TWICE, so the payer asks the
  supplier to return one. Acceptance is still charged once (below).

`tests/test_statement_rails.py` checks each rule. Knos never asks a bank: the payer uploads the file and records the
answer. No bank has taken a file Knos wrote.

## One fee, whichever rail

Acceptance is charged on a deliverable once. `knos.rails.accepted_rows` gives the month's bill one row per agreed
deliverable that was paid, however many records say so. A deliverable paid by bank is value reconciled off chain. A
deliverable the program released says `on_chain`: its fee was taken there and is not charged again. A transfer the
bank sent back is not paid and not charged. `tests/test_statement_rails.py` checks each case against
`knos.billing.invoice`. On devnet every fee is test money.

## The files an accounting system takes

`knos statement export ap-statement.json --format FORMAT`. Every file is a file export, not an integration.

| Format | What it is | Read on 2026-10-07 from the vendor's page | Not confirmed |
| --- | --- | --- | --- |
| `netsuite` | CSV, Vendor Bill import: one bill per agreed line | [Vendor Bill Import](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N427250.html): a unique External ID on every line, mapped to Reference No.; Vendor; the Expenses sublist's Account, Amount and Memo; currency comes from the vendor record. A Purchase Order field exists and cannot be mapped together with the Expenses sublist, so the file carries the order in the memo. | the date format (the page names none), the body field Memo |
| `quickbooks` | CSV, bills import | [Import bills](https://quickbooks.intuit.com/learn-support/en-ca/help-article/import-transactions/import-bills-quickbooks-online/L4Q6QWsRw_ROW_en): the mandatory columns Bill no., Supplier, Bill Date, Due Date, Account, Line Amount, Line Tax Code; the date format is chosen at import; the page names no purchase-order column | the optional columns Line Description and Memo |
| `generic` | CSV, every line with its state, its ids, `po_reference`, `grn_reference` and assurance | Knos's own format | nothing |
| `match` | CSV, every line with `po_number`, `grn_reference` and `match` | Knos's own format | nothing |
| `ariba` | XML, one cXML InvoiceDetailRequest of the agreed lines | Two published samples of the cXML invoice, neither of them SAP's own page: [Coupa's sample with backed and unbacked lines](https://compass.coupa.com/en-us/products/product-documentation/supplier-resources/for-suppliers/integration-resources/standard-invoice-examples/sample-cxml-invoice-with-both-backed-and-unbacked-lines) and [TradeCentric's standard invoice payload](https://help.tradecentric.com/hc/en-us/articles/50857376578963-Invoice-Standard-cXML-payload). From them: the header, the order of the request's parts, one `InvoiceDetailOrder` per purchase order, the item's first four children, the summary. | SAP Ariba's own guide and the cXML document type definition could not be read, so the file was held to neither. The place of the `Extrinsic` elements, the `orderID` attribute, and the order's own payload id and line numbers (a statement does not know them). The sender's shared secret is left out on purpose. Best effort, unverified. |

The two older files of `knos audit export` were read again the same day:

- `coupa`: [Invoices Import](https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/coupa-core-flat-files-(csv)/flat-file-(csv)-import/invoices-import)
  confirms the first 24 columns of the Invoice row. **The Invoice Line row Knos writes is not the page's.** The page
  lists Supplier Part Number and Auxiliary Part Number between Description and Price, names the unit column Unit of
  Measure where Knos writes UOM, and has PO Line Number and Match Reference ("three-way match attribute to connect
  with Receipt and Invoice Header"), which the Knos file lacks. The file stays best effort, unverified, until its line
  row is rewritten.
- `sap`: [SAP note 3782347](https://userapps.support.sap.com/sap/support/knowledge/en/3782347) confirms one row per
  item with the invoice id first and the header fields repeated. It names no other column; the template is inside the
  app. Best effort, unverified.

## The purchase-order match

The `match` file has one row per invoice line.

| `match` | Meaning |
| --- | --- |
| `3-way` | A goods-received note is recorded for the line (`knos statement grn --record --receipt ...`) and it matches: the purchase order, the acceptance and the invoice line agree. `po_number` is the order's number. |
| `2-way` | The line is agreed and an evaluation stands behind it, and no order is on record: the receipt of goods and the invoice line agree. |
| `none` | Anything else. `match_why` gives the note's mismatches or the line's own state. |

Accounts payable usually means "order against invoice" by a two-way match. A Knos statement knows the acceptance
before it knows the order, so its two legs are the receipt of goods and the invoice line; `match_legs` names the legs
in every row so nobody has to guess.
