-- One row per customer: its distinct charges, what they add up to, what was refunded, and the difference, in cents.
-- A charge row delivered more than once is one charge (DISTINCT). Amounts become whole cents row by row, before
-- anything is added: ROUND, because 19.99 * 100 is 1998.9999999999998 in floating point and a cast alone drops a cent.
-- Refunds are added up per charge before the join, so a charge with two refunds is not counted twice.
CREATE TABLE ledger AS
WITH once AS (
    SELECT DISTINCT charge_id, customer_id, CAST(ROUND(amount * 100) AS INTEGER) AS cents FROM charges
), back AS (
    SELECT charge_id, SUM(CAST(ROUND(amount * 100) AS INTEGER)) AS cents FROM refunds GROUP BY charge_id
)
SELECT once.customer_id AS customer_id,
       COUNT(*) AS charges,
       SUM(once.cents) AS gross_cents,
       COALESCE(SUM(back.cents), 0) AS refund_cents,
       SUM(once.cents) - COALESCE(SUM(back.cents), 0) AS net_cents
FROM once LEFT JOIN back ON back.charge_id = once.charge_id
GROUP BY once.customer_id;
