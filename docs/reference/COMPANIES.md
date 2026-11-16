<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# Companies: the panels for buyers and suppliers

**In plain words.** The app has panels for a company that buys work or sells it. This page says what each panel does and what is real today. Everything runs on devnet with test money.

No company uses these panels yet. No bank has taken a file they make, and no finance system has imported one.

## Statements

The statements panel (`web/statements.js`) shows what an account was paid, or paid out, in one month. It reads
`statements/<login>.json` from the site and builds the table and a CSV in the browser. Nothing is sent anywhere.

From the command line, `knos audit show <order>` gives one deliverable as four linked records: authorisation,
acceptance, the commercial record and the settlement status. `knos audit export --owner <org> --from --to` writes a
month as a hash-chained CSV or JSON, and `knos audit verify` finds an edited or removed row. Both read the payment
program's log lines on Solana ([`src/knos/audit.py`](../../src/knos/audit.py)).

What is real today:

- The files for NetSuite, SAP, Coupa and QuickBooks are written from each product's public pages. None has been
  loaded into any of them. The SAP and Coupa files are best effort and unverified.
- A statement carries GitHub's numeric ids. It holds no names.
- An export reads the newest 1,000 transactions of the payment program. An owner with older orders is refused, or
  gets a file marked partial (`--partial`).

## Bank transfers

The rails panel (`web/rails.js`) turns an approved statement into a payment file for the payer's own bank: one ISO
20022 credit transfer (pain.001.001.09), one transfer per supplier. `knos statement pay --rail bank` writes the same
bytes. The panel moves no money: the payer uploads the file to their bank.

Every file is checked against two published guides before it is written (`knos.rails.check`): Payments Canada's
[usage guideline](https://www.payments.ca/sites/default/files/CustomerCreditTransferInitiationV09%28pain.001.001.09%29.pdf)
and Nordea's [message implementation guide](https://www.nordea.com/en/doc/nordea-message-implementation-guide-cap-pain.001.001.09.pdf).
Each IBAN's check digits are verified too. No file was run through the official schema, which is not in this repository. No bank has taken a file this code wrote.

`knos statement status --from bank-answer.xml` reads the bank's answer. An answer that is not clear is held as unknown,
never as a refusal. A deliverable is charged the acceptance fee once, whichever rail paid it.

## Approvals

The approver's screen (`web/approver.js`) is for the person who approves an invoice. It reads the statement and the
invoice that you drop or paste. It asks nobody anything, and it works signed out.

Each invoice line is one row, from the supplier to the payment status. Every line whose policy is not met goes into one
exception queue, with its reason in one sentence. A line over its purchase order, or over the limit the approver typed,
is flagged as advice only: nothing enforces it.

`knos statement approve` records a name and a role as they are typed. Nothing checks them.

### Private repositories

For a private repository the agreed checks run on a runner inside the buyer's network
([`examples/private/knos-private.yml`](../../examples/private/knos-private.yml)). Two files leave: a record of the
verdict and hashes, and the forge's signed token. The record holds no source code and no log line.

`python -m knos.private run` runs the whole path on one machine against a simulator. No customer has run the workflow,
and no enterprise instance's token has been verified.

## The console

The Buy page (`#buy`, `web/buyer.js` and `web/console.js`) is for the person who authorises a payment, and for the
supplier on the other side. It has four tabs: Offers, Budgets, Approvals and Invoice. It reads public data only and
sends nothing to Solana.

Before funding, the page shows the fee as an amount and as a share of the order. It says whether the funding would pass
the Balance's limits, and lists every earlier order for the same issue.

What the page cannot tell you:

- The budget shown is a reading at one moment. Someone else can spend between the reading and the comment.
- The page does not read `.knos/policy.yml`. The command job checks it when the comment runs.
- Today one person answers when something fails. There is no support contract.

## Netting and reserves

Netting adds up small accepted results off chain and pays their sum in one release per supplier per period (`knos net`,
[`src/knos/netting.py`](../../src/knos/netting.py)). It changes no program: it uses knos_meter's batches and knos_pay's
orders as they are.

A reserve is money a buyer locks for one supplier before the work, with the comment `/knos reserve`. Netted work draws
on it in tranches, and what is not drawn goes back to the buyer after the deadline. Without a reserve, the supplier
carries the buyer's credit risk up to an exposure limit.

What is real today:

- In the simulator, 999 accepted outcomes of 0.32 were paid as one release of 319.68 in 24 transactions
  (`tests/test_netting.py`).
- On devnet one period of 20 outcomes was netted and paid as one order of 6.40. One test account was both buyer and
  supplier.
- No published workflow asks for the release's tokens yet.

## Enforcement

The enforcement panel (`#enforcement`, `web/enforce_view.js`) is one table. Each row is a route that can set money aside
or move it. Each column is a restriction a buyer can state. Each cell says what holds it:

| class | what it means |
|---|---|
| program | an instruction of a deployed program refuses it |
| workflow | a job of the pinned workflow refuses it before GitHub signs |
| advisory | a file or a command says so, and nothing stops it |
| outside | outside the policy boundary, by intent |

The table lives in [`src/knos/enforce.py`](../../src/knos/enforce.py). `knos controls matrix` prints it, and
`python -m knos.enforce --markdown` prints it as one page. Every cell that is not `outside` names a test that tries to
get round it (`tests/test_enforcement.py`).

A funding by comment asks the buyer's procurement files before GitHub signs (`flow._gated`). A standing offer is asked
through `knos.approvals.gate`, and every other order through `knos.approvals.gate_order`. Nothing on chain checks these
files, so a wallet that funds an order itself is held only by its Balance's limits.

## Vendors

The vendor pages (`#vendor=<agent>`, `web/vendor.js`) show each agent the [Agent PR Index](INDEX.md) counts: its
numbers with their sample, a right of reply, its disputes and how it earns the supplier badge.
`python scripts/agent_pr_index.py vendors` writes them to [`docs/vendors.json`](../vendors.json) from the published
index files.

The index counts what GitHub recorded against what a pull request's description said. It does not rate the code or the
vendor, and a failed check is not always a failed test.

An agent vendor never pays for a row and cannot pay to change one. A reply or a dispute costs nothing. A dispute that
finds a miscount changes the row, and [INDEX.md](INDEX.md) lists the change.

The badge is the vendor's own record ([SUPPLIER.md](SUPPLIER.md)). It stays grey while the vendor runs only the free
check on its own pull requests. It turns green when work is accepted under a funded order.

## What none of these panels has

- Single sign-on on the public site. These panels have no accounts: identity is GitHub's and a wallet's.
- A legal entity to sign with. Knos has none, and no support agreement.
- A connection to any finance system or bank. The panels make files; nothing sends them.
- Real money. Devnet only.
