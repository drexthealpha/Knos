# Netting: many small outcomes, one release

A 0.32 agent call cannot carry a fee floor of 0.05 and transactions of its own. The escrow takes no job under 1.00
and no order under 5.00, so a single 0.32 outcome cannot be paid on chain alone at all. Netting lets small accepted
outcomes accumulate off chain and pays their sum in one release per supplier per period. **No program changes:** it
uses knos_meter's batches and knos_pay's orders as they are. Money on devnet is test USDC.

Code: [`src/knos/netting.py`](../src/knos/netting.py). Test: [`tests/test_netting.py`](../tests/test_netting.py).

## How a period runs

| step | command | what happens |
|---|---|---|
| open | `knos net open BOOK --buyer ID --seller ID --month 2026-10 --cap 500` | a period between one buyer and one supplier, with a cap |
| add | `knos net add BOOK outcomes.jsonl --events LOG` | accepted outcomes under 20.00, each with its evidence id (sha256 of the signed token or receipt) |
| dispute | `knos net dispute BOOK --evidence ID --reason "..."` | that line leaves the net; every other line stays payable |
| close | `knos net close BOOK --other THEIR_BOOK --ledger PAIR_LEDGER` | both copies must come to the same root; prints the net, the fee, the two anchoring audiences and the release's terms; appends the period to the pair's meter ledger file (a period of seq 1 needs the month's batch 0 in that file before it, or nothing is written) |
| statement | `knos net statement BOOK` | every period: open or closed, lines, net, fee, root, and the table below |

Each side keeps its own book, from what it received. An outcome is one deliverable: an order and a milestone, accepted
once. `add` refuses, line by line and by name:

- a deliverable or an evidence id that any period of the book already holds (duplicates are refused across periods);
- a deliverable the events log already counts as accepted by another recording mode ([EVENTS.md](EVENTS.md));
- an amount of 20.00 or more (fund an order for it), or one that would take the period past its cap.

`close` builds the period as a format 2 meter batch: every field of every line is under one 32-byte root
([METER.md](METER.md)). A disputed line stays in the batch, marked `disputed`, with a value of nothing, so nobody can
later say it was never there. If the two books differ, `close` names the lines that differ and closes nothing. A net
under 5.00 stays open: the escrow takes no order that small.

## The one release

The instrument is an **order funded from the buyer's Balance**, not a standing order: a standing order pays one fixed
rate per pull request, and a period's net is not known until it closes.

1. **Anchor.** The buyer's workflow sends the batch to knos_meter (`RecordBatch`), the supplier's sends its claim
   (`ClaimBatch`). The same running hash in both accounts means both acknowledged the same root.
2. **Fund.** One order of exactly the net, funded from the buyer's Balance. Its terms carry the root, the count, the
   accepted count, the value, the pair and the period; the program stores their hash. The fee is taken here, on top.
3. **Pay.** One pay token from the order's pinned workflow names the order, that terms hash and the supplier. The
   program pays the supplier and closes the order.

## What is enforced, and where

| | enforced on chain | not enforced on chain |
|---|---|---|
| the cap | The buyer's Balance refuses an order above the cap its wallet set (knos_pay, error 93). | That the Balance holds the money: its wallet can withdraw until the order is funded. |
| the release | One order of exactly the net, paid only by a token naming the order, the terms hash fixed at funding, and the supplier. | That the buyer funds it at all. |
| the root | knos_meter keeps the buyer's batch and the supplier's claim; equal running hashes mean the same root. | The link from the release to the batch: the terms name the root and the program stores their hash. A reader compares them; knos_pay does not read knos_meter. |
| each line | Committed by the batch root: any line is proved under it (`knos meter prove`). | No line is escrowed one by one. No program reads a line. |
| duplicates | A batch number is used once per pair and month. | Refused by the book and by the events log both sides acknowledge, not by a program. |
| the fee | 0.30% of the net, at least 0.05, once, taken when the order is funded. | Volume rates: a rebate by contract. |

**The supplier carries the buyer's credit risk inside a period, up to the cap.** Work is delivered before the release
is funded. A supplier that does not want that risk asks for a smaller cap or a shorter period, or for an order funded
before the work. A dispute after a period closed is a correction in a later batch ([DISPUTES.md](DISPUTES.md)); netting
itself does not yet carry a correction from one period into the next.

## Measured in the simulator

`tests/test_netting.py::test_a_thousand_outcomes_settle_as_one_release_on_the_programs_as_they_are` runs the built
programs in LiteSVM: 1,000 outcomes of 0.32, one of them sent twice (refused), one disputed.

| | netted | each outcome singly |
|---|---|---|
| outcomes paid | 999 in one release of 319.68 | 0: the escrow takes no job under 1.00 |
| fee | 0.95904 (0.30% of 319.68; the floor does not bind) | 49.95 if the 0.05 floor alone applied to each of the 999 |
| transactions | 24: two tokens verified and two batches anchored, one token and one funding, one token and one payment | 11,988: 12 for one funded and paid order, 999 times |
| meter fee | 0: 1,000 evaluations are inside the month's free 100,000 | the same |

Past the free 100,000 evaluations a month, anchoring costs the buyer 0.002 for each line of the batch, from prepaid
credits: on a 0.32 outcome that is 0.6% beside the 0.30% acceptance fee.

## Not built

- No published workflow asks the forge for the release's fund and pay tokens yet: `close` prints the audiences and the
  terms, and the simulator test sends them. On devnet one period has been netted, at the public program ids, between
  two wallets of Knos's own release run (0.3.19), with one GitHub account as both buyer and supplier: 20 outcomes of
  0.32 the run itself made up, period 202610.1, anchored by the [buyer](https://explorer.solana.com/tx/56iBxBoqnSnVJ4pZf8PDQw6oNXdUb9WFD8XPxbMSPWs693iXMkXbnLhSsjaRA26pPPZERzAhCSXitj5kMUMJjpCL?cluster=devnet)
  and the [supplier](https://explorer.solana.com/tx/DwtaXvibQ8bFVyTW5X1UeXwEstREPW7HJX4sjMKLoSzeAJy7ML4q4QYj5HyS6vQ5thkFprP2CkZhjKXUrK5RCoC?cluster=devnet)
  through attest.yml, then one order of 6.40 [funded](https://explorer.solana.com/tx/4zzdjLJx8YPK1DkZNGMbZEDpiFm55f7VavAgPcVzaY3mJPHquHmSyhoKRspEDnMaQSnpXgogC23KnBNVUU943P1u?cluster=devnet)
  from a capped Balance and [paid](https://explorer.solana.com/tx/49ydAiiexCVrXQNArt1LuDoqY3mATmKbmx8i5kT8EQdtyHQH64HqFJ4Gxnqmg3PwCtVsu8sXY8YunmU8Aypoqqgr?cluster=devnet)
  to the supplier's wallet, on tokens a workflow of the run's own repository asked for (it signs the audience it is
  given). The fee taken was 0.40, the rule of knos_pay 2.1, which the public id ran then; `close` prints the 2.2 rule.
- No carry of a closed period's correction into the next period's net.
- One payee per release (an order takes up to four; netting uses one).
