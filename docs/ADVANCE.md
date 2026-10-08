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
| `knos advance quote advance-offer.json --period BOOK` | the supplier | prices a closed, reserved netting period as a receivable (below). |

The module is [`src/knos/advance.py`](../src/knos/advance.py), and `src/knos/cli.py` registers its commands.
`advance.offer`, `advance.quote`, `advance.period_quote`, `advance.take_ixs` and `advance.status` are the same things
as functions, and the tests use them.

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

## Selling a closed, reserved netting period

A netting period ([NETTING.md](NETTING.md)) bound to a reserve is a receivable with locked money behind it: at close
it is owed whole tranches from its reserve order. The supplier can sell that instead of waiting for the draws:

| command | who runs it | what it does |
|---|---|---|
| `knos advance quote advance-offer.json --period BOOK` | the supplier | prices the last closed period from the book and the reserve order as the chain has it now; sends nothing |
| `knos advance take advance-offer.json --period BOOK --order RESERVE --payee ID --keypair ... --advancer-keypair ...` | both | the same one transaction: the financier pays, the supplier's bound wallet signs `Assign` on the reserve order |

The quote is refused, with the reason, for a period that is open, unsecured, already settled, under one tranche, over
the offer's cap, or whose reserve is gone, past its deadline, under notice, already assigned, or holds less than the
period is owed. What the period left undrawn is not sold.

The test's numbers: a reserve of 100 test USDC in tranches of 20, five outcomes of 9.50. The period draws 40.00 and
leaves 7.50 undrawn. At a discount of 2% the financier pays the supplier 39.20 and collects the two draws, 40.00.

This is what trade finance calls factoring without recourse: the buyer of the receivable, not its seller, absorbs
the loss if it is not paid ([Allianz Trade](https://www.allianz-trade.com/en_US/insights/invoice-factoring.html), which
puts a factor's fee at 1% to 5% of the invoice). No rate is suggested here: the financier writes its own in its offer.

### Who carries which risk

| who | what it carries |
|---|---|
| buyer | Its money is locked in the reserve order from before the work. It gets back what no draw took, after the deadline, and nothing sooner. |
| supplier | After selling the period: the discount, and nothing else of that period. Without a sale: that the draws are signed before the reserve's deadline, and what the period left undrawn (under one tranche). |
| financier | It paid the supplier and collects the draws. It loses if the judge the order pins signs no draw before the deadline: the money then goes back to the buyer, and the program gives the financier no claim on anyone. |
| Knos | No money at any step: it funds nothing, lends nothing, holds nothing, guarantees nothing and charges nothing for the sale. |

`Assign` moves every later payment of the reserve order to that supplier, not one period's. The financier collects
each draw until it assigns the order back, which only it can sign; a supplier that sells one period of a reserve
that will serve several should agree that hand-back first, or use one reserve for each period it sells.

Both ends run in the simulator
(`tests/test_advance.py::test_a_closed_reserved_period_is_sold_once_the_draws_pay_the_financier_and_an_unsigned_draw_is_the_financiers_loss`):
the draws pay the financier and never the supplier a second time; and when no draw is signed, the buyer has the
whole reserve back at the deadline and the financier, who paid 39.20, collects nothing.

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
- A sale of a netting period on devnet: `quote --period` and the take against a reserve order have run in the
  simulator only. No financier exists.
- An advance between two parties. The one run on devnet was between two wallets of the same operator, and its
  acceptance token came from a workflow of that operator's own repository that signs the audience it is given.
