-- Near miss: everything is right except that amounts become cents with a cast alone. 19.99 * 100 is
-- 1998.9999999999998 in floating point, so that charge is entered as 1998 cents. The worked example has no such amount.
CREATE TABLE ledger AS
WITH once AS (
    SELECT DISTINCT charge_id, customer_id, CAST(amount * 100 AS INTEGER) AS cents FROM charges
), back AS (
    SELECT charge_id, SUM(CAST(amount * 100 AS INTEGER)) AS cents FROM refunds GROUP BY charge_id
)
SELECT once.customer_id AS customer_id,
       COUNT(*) AS charges,
       SUM(once.cents) AS gross_cents,
       COALESCE(SUM(back.cents), 0) AS refund_cents,
       SUM(once.cents) - COALESCE(SUM(back.cents), 0) AS net_cents
FROM once LEFT JOIN back ON back.charge_id = once.charge_id
GROUP BY once.customer_id;
