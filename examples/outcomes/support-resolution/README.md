# Support resolutions, counted under agreed terms

Every ticket, customer and help desk in this folder is made up. Nobody bought this.

A supplier's agent answers support tickets and bills per resolution. The buyer and the supplier agree, before the
work, when a ticket counts. The meter counts by that rule, and the supplier's invoice is set against the count.

    tickets.json   ten tickets as a help desk might export them (one is in the file twice)
    terms.json     when a ticket counts; its hash is the policy every evaluation names
    invoice.csv    what the supplier billed: eight lines at 0.99

**The terms.** A ticket is one accepted resolution when the agent marked it solved, no person took it over (no
escalation, no human reply), the customer did not come back for 72 hours after `solved` (no reopening, no further
message), and those 72 hours have passed. The customer's confirmation counts, and so does leaving without asking for
more. A ticket is billed once. [docs/OUTCOMES.md](../../docs/OUTCOMES.md), "Support resolutions", names the two
published definitions this mirrors.

**Run it** from the repository's root:

    python scripts/outcome_support.py evaluate
    python scripts/outcome_support.py batch
    python scripts/outcome_support.py statement --out out

| ticket | what happened | verdict |
|---|---|---|
| T-1001 | solved, the customer said so | accepted |
| T-1002 | solved, the customer left (in the file twice: one ticket) | accepted |
| T-1003 | reopened 20 hours after solved | rejected |
| T-1004 | the customer asked for a person | rejected |
| T-1005 | solved 30 hours before the export | not judged yet: the window is open |
| T-1006 | the customer wrote again 50 hours after solved | rejected |
| T-1007 | reopened 200 hours after solved, after the window | accepted |
| T-1008 | a human agent answered before it was solved | rejected |
| T-1009 | the agent asked a question, the customer never replied | rejected |
| T-1010 | solved, the customer said so | accepted |

10 tickets: 4 accepted, 5 rejected, 1 not judged yet. The batch holds 9 evaluations worth 3.96. Of the invoice's
eight lines (7.92), four are agreed (3.96), two are disputed, one is a duplicate and one has insufficient evidence.

**What this cannot check.** It reads a file, not a help desk: nothing here shows that an export is true. Whether an
answer was right is in no ticket state. `tests/test_outcome_support.py` holds every number above.
