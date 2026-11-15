-- To be written. Input: charges(charge_id, customer_id, amount) and refunds(refund_id, charge_id, amount).
-- Output: the table below, one row per customer. See README.md.
CREATE TABLE ledger (customer_id TEXT, charges INTEGER, gross_cents INTEGER, refund_cents INTEGER, net_cents INTEGER);
