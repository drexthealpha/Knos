# Advance: a third party pays the supplier now and collects from the order

**Not offered by Knos: a third party can do this today with the program as it is.** Knos lends nothing, holds
nothing and charges nothing for it. No advancer exists. One advance has run on devnet, at the public program ids,
between two wallets of Knos's own release run (0.3.19), so it shows the mechanism and no market: an order of 5.00 test
USDC, the take in [one transaction](https://explorer.solana.com/tx/2oQRB85o6WbZ9T5XXwHpsb13EgQypHK4xKJErNmURT1Zujn1bB6oE84ENiMgT6pRkh79fupPf7VRzm8WPBpe5kAZ?cluster=devnet)
(4.90 to the supplier's bound wallet, and `Assign`), and the acceptance that [paid the advancer 5.00](https://explorer.solana.com/tx/5BLLtaDDBxWxucygnHuuNkAtir7CHfWqpdgQoxnyJg2p1uk1zbaViDbuRDaogjVbrz8cSzYxPwKLBCyDGa4RDuMm?cluster=devnet).
Everything here is tested in the Solana runtime (LiteSVM) with test USDC:
`python -m pytest -q tests/test_advance_offer.py tests/test_advance.py`.

A supplier with a funded order waits for the judge. An advancer (anyone with money and a view on the supplier) pays
the supplier now, less a discount, and the order pays the advancer when the work is accepted. The only instruction
of `knos_pay` this uses is `Assign` (24): a payee names the wallet that receives this order's payment in his place.

## The three commands

| command | who runs it | what it does |
|---|---|---|
| `knos advance offer <wallet> --rate 2 --cap 500` | the advancer | writes `advance-offer.json`: its discount, its cap per order, the judges and the assurance it accepts. Nothing is sent. |
| `knos advance take advance-offer.json --order <address> --payee <GitHub id>` | the supplier | prints the quote, and every reason there is none. With `--keypair` and `--advancer-keypair` it sends the one transaction. |
| `knos advance status --order <address> --payee <GitHub id>` | anyone | where the advance stands, from the chain alone. |

The module is [`src/knos/advance.py`](../src/knos/advance.py). The commands are registered once `src/knos/cli.py`
lists the module; until then `advance.offer`, `advance.quote`, `advance.take_ixs` and `advance.status` are the
interface, and the tests use them.

## The offer

`knos.advance-offer/1`, a file the advancer publishes wherever it likes. Knos keeps no list of offers.

| field | meaning | checked against |
|---|---|---|
| `advancer` | the wallet that pays and collects | the signer of the transfer |
| `rate_bps` | the discount on the share advanced against, rounded up | arithmetic |
| `cap` | the most advanced against one order | the order's amount on chain |
| `evaluators` | the judges it accepts, each `<workflow repository>@<commit>`, or `*` | the order's pinned workflow on chain |
| `assurances` | how the judge must have run: `black-box`, `hermetic`, `in-process` | the receipt of an acceptance already signed; unknown while the work is in review |
| `min_seconds_left` | the least time before the order's deadline | the order's deadline and the chain's clock |
| `holdback` | whether it advances against an order with a warranty | the order on chain |

The quote refuses an order that is not open, is already assigned, is a standing offer, is under notice, is in
another token, is over the cap or is too near its deadline, and says which.

## One transaction

`take` builds one transaction with two signatures:

1. the advancer transfers the share less its discount to the supplier (a plain token transfer);
2. the supplier's bound wallet signs `Assign`, naming the advancer.

A transaction lands whole or not at all. An advancer who cannot pay gets no assignment; a wallet that is not the
supplier's bound wallet gets no money. After it, the supplier cannot take the assignment back or assign the order a
second time: only the advancer can pass it on.

Both keys in one command is a rehearsal. Two parties on two machines must pass the transaction between them inside
one blockhash (about a minute) or use a durable nonce: that hand-over is not built.

## The three ends

The example's numbers: an order of 100 test USDC, a discount of 2%, so the supplier receives 98 at the take.

| end | what happens on chain | supplier | advancer | funder |
|---|---|---|---|---|
| accepted | the judge's signed acceptance arrives; `PayOrder` pays the assignee | keeps 98 | paid 98, collects 100 | paid 100 and the order's fee |
| rejected | no acceptance is signed; the funder gives notice (`Cancel`) and is refunded when the notice ends (7 days) | keeps 98 | paid 98, collects 0 | refunded the amount and the fee |
| expired | the deadline passes; anyone sends `RefundOrder` | keeps 98 | paid 98, collects 0 | refunded the amount and the fee |

Nothing pays both. After the take the program routes the supplier's share to the advancer whatever address the
judge's token names; a payment that names the supplier's own wallet is refused; once the order is refunded a late
acceptance pays nobody. The tests hold each of these.

An acceptance already signed and not yet carried to the program can be advanced against in the same way: the order
is still open, so `Assign` takes, and the same signed acceptance then pays the advancer. That is the least risky
advance, and the shortest: it lasts as long as the relay takes.

An order with a holdback pays the advancer the part due at acceptance and the rest after the warranty. A revert
inside the warranty sends the holdback back to the funder: [`examples/advance`](../examples/advance/README.md).

## Recourse

**None on chain.** The program gives the advancer no claim on the supplier and none on the funder. If the work is
rejected or the order expires, the loss is the advancer's own. Whatever the two agreed off chain is between them;
Knos is no party to it and enforces none of it.

What an advancer should check first:

- **The supplier's record** ([RECORD.md](RECORD.md)): what was accepted, rejected and reverted, with the sample.
  Today no record holds a Knos order of an outside supplier, so there is nothing to price a supplier on yet.
- **The terms**, by their hash: what the judge will accept, and whether the work can meet it.
- **The deadline**: an order nobody accepted goes back to its funder then.
- **The judge**: the workflow repository and commit the order pins, and who controls it.
- **The funder's notice**: a funder who signs `Cancel` shortens the deadline to 7 days from the notice.

## What Knos would charge, as a design and not an offer

Knos charges nothing for an advance today, and nothing in the program can collect a charge for one. If it ever
charged, the design is an origination fee on the amount advanced (what the supplier receives at the take), paid by
the advancer, once, in the same transaction, and never by the supplier. No rate is set. The order's own Acceptance
fee is unchanged by an advance: the funder paid it at funding.

## What is not built

- The hand-over of a half-signed transaction between two machines.
- A list or a market of offers. An offer is a file.
- A bond: an advancer posts nothing, and nothing makes it pay. The single transaction is the only guarantee.
- An advance against only the holdback after acceptance: `Assign` after a payment moves nothing.
- A check of the offer's `assurances` on chain: the order does not record how its judge will run.
- An advance between two parties. The one run on devnet was between two wallets of the same operator, and its
  acceptance token came from a workflow of that operator's own repository that signs the audience it is given.
