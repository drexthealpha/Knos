# The Pilot: one buyer, two suppliers, 30 days, one reconciled invoice

**Close a supplier's invoice with evidence both sides can check.**

The neutral meter for AI agent work: neither side keeps the count.

This is the one thing Knos offers for money today. It is an offer, not a record: **nobody has bought it, nobody has
been asked, and there is no legal entity to invoice from yet.** Nothing on this page reports demand. The last
section says what blocks it.

## How it starts: shadow mode

A Pilot starts in shadow mode. For the first period the count runs beside the invoices the buyer already receives
and changes nothing: no money moves through Knos, nobody's process changes, no supplier is paid differently, and
the buyer approves its invoices exactly as before. Shadow mode asks the buyer for no trust and no money. It is
free, with or without a Pilot after it, inside the Meter's free allowance.

What shadow mode produces is two numbers side by side for each supplier, the supplier's invoice count and the
neutral count, and every line where they differ. The first line the two sides have to settle between them is the
reason to buy the Pilot: the Pilot is the same work done for two suppliers, for 30 days, ending in one reconciled
invoice and the findings as numbers, with someone answerable for them. A shadow count that finds no difference is a result too, and
the buyer should then not buy the Pilot.

No shadow count has been run with anyone, and none is published.

## Who it is for

A company that buys agent work per outcome from two or more suppliers (agent vendors, agencies, contractors
paid per merged change or per milestone) and has their invoices to reconcile. The person who signs is whoever
must authorise those payments and defend them afterwards: an engineering director or a finance controller.

It is not for a company with one supplier (there is nothing to compare), for work billed by the hour or the seat,
or for a maintainer with a bounty: the free check and `/knos fund` already serve that.

## What the buyer gets: four deliverables

A Pilot is **one buyer, two suppliers, 30 days, one reconciled invoice, and quantified findings.** Two suppliers
are the scope the price covers; a third is a second Pilot or a Supplier connection under a contract.

| | deliverable | what it is |
|---|---|---|
| 1 | **One reconciled invoice** | The buyer's accepted work for the 30 days, from both suppliers, set against what each billed, as one list of deliverables. Each line has the order, the milestone, the artifact, the policy version that judged it and the verdict. A deliverable is counted once, whatever number of pull requests carried it. |
| 2 | **A mismatch list** | Every difference between what was accepted and what was billed, named: billed and not accepted; accepted and not billed; billed twice; judged differently by the two sides. A mismatch is a dispute line, never an invoice line. |
| 3 | **A statement both sides verify** | For each supplier, one statement that the buyer computes from its ledger and the supplier computes from its own, to the same totals (`knos meter reconcile`, [METER.md](METER.md)). The statement counts only what both sides have and describe alike. |
| 4 | **Quantified findings** | The four numbers below, before and after, written down with their sample sizes, and given to the buyer whether or not they flatter Knos. |

Each statement can be checked from the two ledger files alone. Totals are also written to Solana devnet as test
data, to show the mechanism; devnet keeps no promise about its history, so nothing in the Pilot depends on it.

## What the buyer does

1. Names the two suppliers in scope and one repository per supplier relationship.
2. Installs Knos in each repository **by a pull request** it reviews and merges: one workflow file and one policy
   file, no secret ([INSTALL.md](INSTALL.md)).
3. Writes the acceptance terms for each deliverable before the work starts: the checks that must pass and the
   paths that may change. Templates exist; the buyer chooses and edits.
4. **Keeps a ledger**: one file in a repository of its own, which its workflow appends to.
5. Gives the last closed month of invoices from the same suppliers, as the baseline.
6. Names one person who approves invoices, for an hour at the start and an hour at the end.

## What each supplier does

1. Agrees to the terms before starting each deliverable. They cannot be changed after funding, by either side.
2. **Keeps a ledger of its own**, in a repository of its own, and records its own count of the month. The buyer
   does not need to show the supplier its file for a difference to become visible.
3. Sends its invoice for the period as it normally would.

A supplier pays nothing. A supplier who will not keep a ledger is out of scope, and the Pilot says so in its
report: with one ledger there is nothing for the two sides to agree on.

## What is measured, before and after

| measure | how it is taken | before | after |
|---|---|---|---|
| Invoice preparation time | hours the buyer's and each supplier's people spend preparing and checking one period's invoice, as they report it | the last closed month | the Pilot's 30 days |
| Disputed lines | invoice lines questioned, corrected or credited, out of all lines | the same month | the mismatch list |
| Acceptance-to-approval time | days from a deliverable being accepted to its invoice line being approved | the same month | from the time of the accepting run and the buyer's own approval record |
| Repeat use | whether the buyer and each supplier run a second period without being asked | not applicable | recorded 30 days after the end |

## The benefit to demand before buying: three to one

A buyer should not go on from a Pilot to a contract unless the findings show a benefit of three times the price,
on the buyer's own numbers. The rule as one worked line, at the example of [MARKET.md](MARKET.md), section 6:

| a year's price | × 3 | the benefit the findings must show |
|---|---|---|
| 130,000 USD (Control Business 80,000 + Verify 50,000, the greater of Meter 24,000 and Verify 50,000) | × 3 | 390,000 USD a year |

For the Pilot alone the same line is 2,500 × 3 = 7,500 USD of benefit found in the 30 days. The benefit is the sum of
what the four measures above are worth to the buyer: hours no longer spent, lines no longer paid twice or paid for
work that did not meet its terms, days no longer waited. `knos bill estimate` prints the price and the benefit to
demand for any plan and volume. **Knos has not shown this benefit for anyone.** Nobody has measured it, and a Pilot
that finds less will say how much less, and that the buyer should not buy.

## What it costs

2,500 USD for one buyer and two suppliers, for 30 days, invoiced off chain in ordinary money. The suppliers pay
nothing. No fee is taken on chain: any settlement during a Pilot is on devnet in test USDC, and a fee in test
money is not revenue.

**The 2,500 USD is credited against year one.** A buyer who goes on to an annual contract
([MARKET.md](MARKET.md), section 3) pays that year's invoices less the 2,500 USD already paid: on the Team plan,
22,500 USD of Control in its first year. The Pilot commits the buyer to no contract, and a buyer who stops after it owes nothing
more. No contract exists to credit it against today.

## What it does not include

- Private repositories under a contract, single sign-on, private deployment, a retention period, or a
  service-level agreement. None exists ([CONTROLS.md](CONTROLS.md)).
- Payment of the suppliers in real money. Mainnet is not touched.
- A second person to call. Support is the founder.
- A security review of Knos by anyone outside it. There has been none.

## The blockers, plainly

- **No legal entity exists to invoice from.** No company has been formed, so the invoice in "invoiced off chain"
  cannot be issued today, and nothing can sign terms or a data-processing agreement. Until that changes, the Pilot
  cannot be sold.
- **Nobody has bought it.** No buyer has been asked. Whether any buyer has this problem badly enough to pay is
  unknown; [submission/INTERVIEWS.md](submission/INTERVIEWS.md) is the kit for asking.
- **The founder is one pseudonymous person.** A buyer's procurement process may refuse on that alone, and would be
  right to ask who answers if he is unavailable. Today: nobody ([TEAM.md](TEAM.md)).
- **It has never been run.** The reconciliation is tested on example ledgers
  ([`examples/meter/`](../examples/meter)); it has not been run on a real buyer's invoices, so the 30 days and the
  price are estimates.
- **Some of what it uses may not be live on the public program ids on a given day.** The batched count and the
  supplier's own count are instructions of the newer builds; the live state is in `web/upgrades.json`, and
  [CAPABILITIES.md](CAPABILITIES.md) gives each capability's stage. The ledger files and the statement need no
  chain at all.
