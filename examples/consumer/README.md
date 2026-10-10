# Use the record without Knos

`consumer.mjs` is a second application, written apart from Knos: Node 20 or later, no package, no code of Knos's. It
reads an acceptance receipt, or a statement's status file, and a Solana cluster, and decides on its own whether the
order is paid, by which transaction, and under which terms hash. All it knows of Knos is two published files: the
receipt's JSON Schema ([`docs/receipt/`](../../docs/receipt)) and knos_pay's IDL ([`idl/knos_pay_v2.json`](../../idl/knos_pay_v2.json)).

    node consumer.mjs receipt RECEIPT.json                 # asks devnet's public endpoint
    node consumer.mjs receipt RECEIPT.json --rpc URL       # asks your own endpoint
    node consumer.mjs status STATUS.json --rpc URL         # every payment on chain a statement's status file records
    node consumer.mjs receipt fixtures/receipt.json --recorded fixtures/order_paid.json   # offline, recorded answers
    node --test test.mjs                                   # its tests, offline

Add `--json` for the decision as JSON. Copied out of this repository, pass `--idl FILE` and `--schemas DIR` with the
two files taken from the release tag. Exit 0: paid, and every claim it checked agrees with the chain; 1: not; 2: wrong use.

## What it checks

1. The receipt fits its version's published schema (versions 4 and 5), and names knos_pay at the IDL's address.
2. The cluster has the receipt's transaction at `finalized` commitment, and it did not fail. It reads every version a
   cluster sends: legacy, version 0 (some accounts come from an address lookup table) and version 1, which Knos's
   relay sends. It asks with `"maxSupportedTransactionVersion": 1`; asked with 0, devnet refuses a version 1
   transaction ("Transaction version (1) is not supported by the requesting client").
3. One of its instructions is knos_pay's PayOrder, SettleOrder or Release (the IDL's tags), and the account in the
   IDL's `order` place is the receipt's order.
4. knos_pay itself logged the payments (`knos3:paid`, `knos3:released`) and the settlement (`knos3:settled`): a line
   printed while another program runs does not count. Payees, wallets, amounts, fee and tip must be the receipt's.
   A truncated log decides nothing.
5. When the answer has token balances, each payee's wallet received its amount.
6. The order's funding before that payment (from the order's own transaction history): the terms hash is the sha256
   of the terms that funding logged, or, for a private order, the hash in the funding instruction's terms argument;
   it must be the receipt's `policy.terms_hash`. The funded amount and the funding transaction the receipt names agree.
7. The receipt's deliverable and settlement ids are the ones the order, milestone and transaction give
   (`docs/CONFORMANCE.md`; the published vectors in `conformance/vectors/ids.v1.json` are in its tests).

For a status file it does 2 to 4 and 6 for each payment on chain, and checks that the line's deliverable is of the
order paid and that its settlement id is that deliverable paid by that transaction. A deliverable id names an order's
milestone in one of two published ways: by the order (a receipt, a meter ledger), or by an audit export's billing key,
the order and the transaction that funded it (`knos audit export`; a witnessed statement takes its line from it). The
milestone is 0, or a standing order's pull request, which the payment logs.

## What it trusts

- The cluster's answers. Ask a second endpoint to remove that.
- That the program at the IDL's address is knos_pay as published: its upgrade authority is a multisig with a time
  lock, so a change is public before it runs.
- Which work was accepted, and why. The forge signs the judge's run, and knos_oidc checks that signature on chain
  before knos_pay pays; this program does not re-read the token.

## Its tests

`test.mjs` runs on `fixtures/order_paid.json`: one order funded from a Balance and paid on the LiteSVM harness
(knos_pay and knos_oidc as built), its receipt, a status file and the answers a cluster would give. The signatures
are numbered stand-ins, since a LiteSVM run has no cluster. `record.py` writes the fixtures again;
`tests/test_consumer.py` also decides an order paid on a fresh harness each run.

devnet's public endpoint is rate limited and "not intended for production applications"
([Solana clusters](https://solana.com/docs/references/clusters)); an order with a long history takes one request
per transaction read. Each request gives up after 30 seconds; a "too many requests" answer is asked again four times,
after 1, 2, 4 and 8 seconds, then reported.
