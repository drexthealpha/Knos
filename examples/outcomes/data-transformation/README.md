# One ledger row per customer, to the cent

Budget: 150 test USDC, paid when the check passes.

**What to deliver.** `transform.sql` in the repository root, in SQLite's SQL. It is run in a database that holds two
tables and must leave a third:

    charges (charge_id TEXT, customer_id TEXT, amount TEXT)     amount is like '19.99'
    refunds (refund_id TEXT, charge_id TEXT, amount TEXT)
    ->
    ledger  (customer_id, charges, gross_cents, refund_cents, net_cents)    one row per customer, whole cents

Our payment feed delivers at least once: the same charge row can arrive two or three times and is one charge. A charge
can have no refund, one, or several. `charges` is how many distinct charges the customer has.

**What we give you.** `examples/`: seven charge rows, three refunds and the ledger they make.

**How it is judged.** The suite in `.knos/acceptance/1/` makes 40 pairs of tables from fixed seeds (5 to 24 customers,
24 to 148 charge rows each), runs `transform.sql` on each in the sandbox and checks properties of the result:

- schema: the five columns, the customer as text, the rest whole numbers;
- key uniqueness: one row per customer;
- row conservation: every customer of the input and no other; the charges counted equal the distinct charges of the input;
- reconciliation: gross, refunds and net add up to the input's totals to the cent, net is gross minus refunds on every
  row, and each customer's row is that customer's own.

The seeds are fixed, so the verdict is the same on every run and either party can run it again. The first case that
fails is named with its seed.

## What is in this folder

`solution/transform.sql` passes all 40. `cheats/special_cases_visible/` is the worked example's answer written down:
bundle 2 (the naive check: the example comes out as expected) accepts it; bundle 1 refuses it on the first case, row
conservation. `near_misses/float_cents/` is an honest attempt that turns `19.99` into cents with a cast alone: it also
passes the example, and bundle 1 refuses it at reconciliation, 17 cents apart on the first case.

[terms.json](terms.json) has the terms in one sentence and as funded. [evaluations.jsonl](evaluations.jsonl) has the
two evaluations as the meter counts them: same order, policy (the hash of the terms) and milestone, a different
artifact, so two ids, one accepted and one rejected.

**What this suite cannot check.** Tables shaped unlike the generator's (other columns, null amounts, currencies), speed
on production volumes, and behaviour in another database engine than SQLite. Fixed seeds make the verdict repeatable
and also make the 40 cases knowable to anyone who can read the bundle; a submission written against exactly those
would have to reproduce 40 ledgers, which is the work. A buyer who wants fresh cases at each judgment trades away the
identical rerun.
