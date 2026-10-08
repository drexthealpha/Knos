# Advance: a financier pays the seller now and collects from the order

A work order with a holdback pays most of its amount when the work is accepted and keeps the rest through a
warranty. A seller who wants all of it at acceptance can assign the order's payment to a financier. The financier
pays the seller off the order, and the order pays the financier.

This uses what knos_pay has today: `Assign` (instruction 24). Not offered by Knos: a third party can do this today
with the program as it is. Knos charges nothing for it and takes no part in the deal between the seller and the
financier. `tests/test_advance.py` runs every step below in the Solana runtime (LiteSVM), with test USDC.

[docs/ADVANCE.md](../../docs/ADVANCE.md) is the whole of it: `knos advance offer | take | status`, the one
transaction that pays the seller and assigns the order together, and the three ends (accepted, rejected, expired).
This page is the case that page leaves out: an order with a holdback, where the transfer is made apart.

## What `Assign` does

- The payee names a wallet that receives this order's payment in his place. The first time, the payee's bound wallet
  signs (`knos claim <address>` binds one). After that only the current assignee can change it: the payee cannot take
  it back, and cannot assign the same order to a second financier.
- It covers one order. Another order of the same seller is not assigned.
- From then on every payment of that order to that payee goes to the assignee, whatever address the judge's token
  names: the part paid at acceptance, and the holdback at release.
- **The assignment has to be made before the order is paid.** A holdback is recorded with the wallets of the payment
  that created it, and `Release` pays those wallets and no other. An `Assign` sent after acceptance, inside the
  warranty, is accepted by the program and moves nothing: the holdback still goes to the wallet the payment
  recorded. So today an advance is agreed while the work is in review, not after it is accepted.

## The steps

The numbers are the test's: an order of 100 test USDC, 20% held back for 30 days, and a financier's price of 2%
(the financier sets it, not Knos).

1. The funder opens the order: `/knos fund 100 holdback 20 warranty 30`.
2. The seller binds a wallet, once: `knos claim <address>`.
3. The seller and the financier agree a price. The seller's bound wallet signs `Assign` for this order, naming the
   financier's wallet. `knos.settle.v2.pay.assign_ix(signer, order, payee_id, to)` builds the instruction; the
   JavaScript client lists it as `Assign` (`sdk/settle/index.js`). The program logs
   `knos3:assigned order=<order> payee=<id> to=<financier>`, and the order's receipt lists it as an amendment.
4. The work is accepted. The order pays 80 to the financier's wallet and records the holdback of 20 for that wallet.
5. The financier pays the seller 98 (100 less its price) with a plain transfer. This is off the order: nothing on
   chain makes it happen, so the two agree whether it is paid at assignment or at acceptance. Paying at acceptance,
   as the test does, means the financier never advances against work that is not accepted.
6. After the warranty anyone sends `Release`: the 20 goes to the financier, who has now received 100 for 98 paid.

## What the financier risks

- **A revert inside the warranty.** If the accepted change is reverted in those 30 days, a judge of the order signs
  `Revert` and the whole holdback, with the fee on it, goes back to the funder. The financier advanced 98 and
  collected 80: it is out 18 test USDC. The program gives it no claim on the seller; getting that back is a matter
  between the two of them, off chain.
- **Time.** The 18 is out for the whole warranty, and the 2 is all the financier earns for it.
- **Before acceptance.** If the financier pays at assignment and the work is never accepted, the order goes back to
  its funder at the deadline and the financier has paid for nothing. Pay at acceptance.
- **An order cancelled with notice** still pays what is accepted before the notice ends; after that it is refunded.

## What the seller gives up

Everything the order pays goes to the financier, not only the holdback, and the seller cannot undo the assignment.
The seller should assign only to a financier it trusts to make the off-order payment, or have it paid first.

## A netting period instead of one order

A supplier paid by netted periods ([docs/NETTING.md](../../docs/NETTING.md)) sells a closed period the same way, when
the buyer locked a reserve for it: `knos advance quote advance-offer.json --period BOOK` prices the period's draws on
its reserve order, and the take assigns that order. The financier then carries the wait for the draws, and the loss
if none is signed before the reserve's deadline; an unsecured period is refused, because no order holds its money.
Who carries what, in four rows: [docs/ADVANCE.md](../../docs/ADVANCE.md#who-carries-which-risk).

## What is not built

- An assignment of only the holdback after acceptance. The program would have to let the recorded wallet of a
  holdback hand it on.
- An escrow for the advance. `knos advance take` puts the financier's payment and the assignment in one transaction,
  which lands whole or not at all ([docs/ADVANCE.md](../../docs/ADVANCE.md)); nothing holds the money longer than that.
- Nobody has financed an order this way; no financier exists.
