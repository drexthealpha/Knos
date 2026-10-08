# Netting: many small outcomes, one release

A 0.32 agent call cannot carry a fee floor of 0.05 and transactions of its own. The escrow takes no job under 1.00
and no order under 5.00, so a single 0.32 outcome cannot be paid on chain alone at all. Netting lets small accepted
outcomes accumulate off chain and pays their sum in one release per supplier per period. **No program changes:** it
uses knos_meter's batches and knos_pay's orders as they are. Money on devnet is test USDC.

Code: [`src/knos/netting.py`](../src/knos/netting.py). Test: [`tests/test_netting.py`](../tests/test_netting.py).

## How a period runs

| step | command | what happens |
|---|---|---|
| reserve | `knos net reserve --buyer ID --seller ID --amount 500 --tranche 50 --balance ADDRESS --issue N` | prints what the buyer's funding run signs to lock money for this supplier before the work; sends nothing |
| open | `knos net open BOOK --buyer ID --seller ID --month 2026-10 --cap 500 --reserve ORDER` | a period between one buyer and one supplier, with a cap, bound to the locked order. Without `--reserve` the period is unsecured, and `--max-exposure` (default: the cap) bounds what the supplier carries |
| add | `knos net add BOOK outcomes.jsonl --events LOG` | accepted outcomes under 20.00, each with its evidence id (sha256 of the signed token or receipt) |
| dispute | `knos net dispute BOOK --evidence ID --reason "..."` | that line leaves the net; every other line stays payable |
| close | `knos net close BOOK --other THEIR_BOOK --ledger PAIR_LEDGER` | both copies must come to the same root; prints the net, the fee, the two anchoring audiences and the release's terms; appends the period to the pair's meter ledger file (a period of seq 1 needs the month's batch 0 in that file before it, or nothing is written) |
| settled | `knos net settled BOOK --period 202610.0 --by ORDER_OR_TRANSACTION` | writes a closed period as paid; it leaves the supplier's exposure |
| statement | `knos net statement BOOK --chain` | every period: open or closed, lines, net, fee, root, reserve funded, consumed and free, the supplier's exposure, and the table below; `--chain` reads each reserve order again |

Each side keeps its own book, from what it received. An outcome is one deliverable: an order and a milestone, accepted
once. `add` refuses, line by line and by name:

- a deliverable or an evidence id that any period of the book already holds (duplicates are refused across periods);
- a deliverable the events log already counts as accepted by another recording mode ([EVENTS.md](EVENTS.md));
- an amount of 20.00 or more (fund an order for it), or one that would take the period past its cap;
- a line that would take a reserved period past what its order holds, or an unsecured book past its exposure limit.

`close` builds the period as a format 2 meter batch: every field of every line is under one 32-byte root
([METER.md](METER.md)). A disputed line stays in the batch, marked `disputed`, with a value of nothing, so nobody can
later say it was never there. If the two books differ, `close` names the lines that differ and closes nothing; the
two must also name the same reserve. An unsecured net under 5.00 stays open: the escrow takes no order that small.

## Who carries the buyer's credit: reserved or unsecured

Every period is one of two things, and `open`, `add`, `close` and `statement` each say which.

**Reserved.** The buyer locks money before the work, as a marketplace escrow does when a client funds a milestone
before the freelancer starts ([Upwork's description of its own](https://support.upwork.com/hc/en-us/articles/360000990428)).
Here the lock is a standing order of knos_pay as it is today: the order's own token account holds the money, no
instruction lets the buyer withdraw it, and its terms name the pair, so `open --reserve` refuses an order funded for
another supplier or for other work. The statement prints, for each period:

| printed | meaning | rule |
|---|---|---|
| `funded` | what the order held when the period was bound to it | read from the chain by `open` |
| `brought` | accepted in the period before on the same order and not yet drawn | under one tranche |
| `consumed` | what this period's accepted, undisputed lines add up to | `add` refuses the line that would pass `funded` |
| `free` | what the period can still accept | `funded = brought + consumed + free`, at every step |
| `exposure` | accepted with no locked money behind it | 0.00 for a reserved period |

At close the period is paid by **draws**, not by a new order: one pay token for each whole tranche of
`brought + consumed`, each paying the supplier one tranche out of the reserve order. `close` prints them. A draw
names the period and its own number where a pull request's number goes, and a standing order pays a number once, so
no draw is paid twice. What is left under one tranche (`undrawn`) is still covered by the lock, and the next period
bound to the same order draws it first.

**What is not consumed returns to the buyer by `RefundOrder` (knos_pay instruction 22).** Anyone may send it once the
order's deadline has passed. It pays everything the order still holds, with the unspent share of the fee, only to
where the money came from: the buyer's Balance, or the wallet that funded it. Before the deadline nothing returns
it. The buyer's `Cancel` (instruction 21) moves the deadline to 7 days from the notice and no nearer; draws still pay
until then. A reserve is locked for at most 90 days, the longest deadline an order takes.

Three limits, stated because the program is unchanged:

- **A draw needs a signature.** The order pins its judge. When that is the buyer's own repository, the buyer can
  withhold the token, and the money then returns to it at the deadline. The reserve proves the money exists and
  cannot go elsewhere; it does not force the release. knos_pay lets an order name a neutral run as a second judge;
  `knos net reserve` does not ask for one and no reserve has been drawn that way.
- **Tranches.** A draw pays exactly one tranche. A small tranche leaves little undrawn and takes more draws; each
  draw is one signed token and its transactions. Undrawn value with no later period before the deadline goes back
  to the buyer: that last part, under one tranche, is the supplier's to lose.
- **The fee.** The escrow takes its fee when the reserve is funded: 0.30% of the reserve, at least 0.05. Each draw
  carries its share and the rest returns with what is not drawn, so a reserve of 16.67 or more costs 0.30% of what
  is drawn. A smaller one pays the floor on the whole.

**A Balance is not a reserve.** The wallet that opened it can withdraw from it (`Withdraw`, instruction 2) until an
order is funded, so `open --reserve` takes an order's address and nothing else.

**Unsecured.** No reserve is bound. The supplier delivers first and carries the whole accepted value until the buyer
funds the release. `--max-exposure` bounds that over the whole book, not one period: a closed period counts until
the supplier writes it `settled`, so a buyer cannot leave period after period unfunded behind a fresh cap. `add`
refuses the line that would pass the limit and says what is already carried.

## The one release

For an unsecured period the instrument is an **order funded from the buyer's Balance** after the close, for exactly
the net. (A reserved period is paid by draws on its standing order, above, and funds nothing new.)

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
| a reserve | The order's account holds the money from before the work. Only a pay token of the judge the order pins moves it to a payee, one tranche a token, each number once. `RefundOrder` returns the rest only to its funder, only after the deadline. | That a draw is signed: a buyer whose own repository is the judge can withhold it. The link from a draw to the batch: the token names the first 40 hex characters of the root, and the program does not read it. |
| the release | One order of exactly the net, paid only by a token naming the order, the terms hash fixed at funding, and the supplier. | That the buyer funds it at all. |
| the root | knos_meter keeps the buyer's batch and the supplier's claim; equal running hashes mean the same root. | The link from the release to the batch: the terms name the root and the program stores their hash. A reader compares them; knos_pay does not read knos_meter. |
| each line | Committed by the batch root: any line is proved under it (`knos meter prove`). | No line is escrowed one by one. No program reads a line. |
| duplicates | A batch number is used once per pair and month. | Refused by the book and by the events log both sides acknowledge, not by a program. |
| the fee | 0.30% of the net, at least 0.05, once, taken when the order is funded. | Volume rates: a rebate by contract. |

**In an unsecured period the supplier carries the buyer's credit risk, up to the exposure limit.** Work is delivered
before the release is funded. A supplier that does not want that risk asks for a reserve. A supplier that wants its
money before the draws sells the closed, reserved period to a financier, who then carries the wait
([ADVANCE.md](ADVANCE.md)); Knos funds none of it. A dispute after a period closed is a correction in a later batch ([DISPUTES.md](DISPUTES.md)); netting
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

`tests/test_netting.py::test_a_period_is_paid_from_a_reserve_locked_before_the_work_and_what_it_does_not_draw_returns_to_the_buyer_at_the_deadline`
runs one reserved period on the same built programs: a reserve of 10.00 in tranches of 2.00, 32 outcomes of 0.32.

| step | on chain |
|---|---|
| lock | 10.05 leaves the buyer's Balance: 10.00 and the fee of 0.05 (the floor) |
| before the deadline | `RefundOrder` is refused (error 83) |
| the period | 31 outcomes fit (9.92); the 32nd is refused as past the reserve |
| close | 4 draws of 2.00 pay the supplier 8.00; 1.92 is undrawn; a second token for draw 1 is refused (error 91) |
| next period | brings 1.92 forward, accepts 0.08, and has one draw of 2.00 that nobody signs |
| after the deadline | that draw is refused; `RefundOrder` to another account is refused (error 88); sent properly it returns 2.01 to the Balance |
| in all | 10.05 locked = 8.00 drawn + 0.04 of fee on the draws + 2.01 returned |

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
- No published workflow signs a reserve's funding or its draws: `knos net reserve` and `close` print the audiences,
  and the simulator tests send them. No reserve has been locked or drawn on devnet.
- A reserve that was topped up is not bound again inside a period: close the period and open the next on it.
- Nothing forces a buyer to sign a draw: a reserve whose judge is not the buyer's own repository is not built.
- No carry of a closed period's correction into the next period's net.
- One payee per release (an order takes up to four; netting uses one).
