# Vendors in the Agent PR Index

<!-- written by scripts/agent_pr_index.py vendors; do not edit by hand -->

One section for each agent the [Agent PR Index](INDEX.md) counts, week of 2026-09-28 (read 2026-10-07): its numbers with their sample, its reply, its disputes, and how it earns the supplier badge. The site shows the same as a page per vendor ([https://drexthealpha.github.io/Knos/#vendor=copilot](https://drexthealpha.github.io/Knos/#vendor=copilot)); the data is [`vendors.json`](vendors.json).

**What the index is not.**

- It is not a rating of defect-free work: a merged pull request with no failed check can still be wrong.
- It is not a rating of the code or of the vendor: it counts what GitHub recorded against what a description said.
- A failed check is not always a failed test or a false claim (INDEX.md, method, points 6 and 7).

**The rule.** An agent vendor never pays for a row and cannot pay to change one. A reply or a dispute costs nothing and changes no number by itself; a dispute that finds a miscount changes the row, and the change is listed in the changelog of [INDEX.md](INDEX.md).

**Earn the supplier badge.** The badge is the vendor's own record ([RECORD.md](RECORD.md)), apart from its index row.

1. **Run the free check on your own pull requests.** One line in your repository's workflow: `uses: drexthealpha/Knos/.github/workflows/supplier.yml@v0.3.25` (docs/RECORD.md, section 3). Gives a check receipt for each pull request; the badge stays grey.
2. **Deliver accepted work under a funded order.** A buyer funds an order; the work passes the terms fixed at funding and is paid on a token the forge signed. Gives an acceptance receipt for each delivery (docs/RECEIPT.md); the badge turns green, with its sample.

## claude-bot

**Row.** 10 of 165 merged had a failed check: 6.1%, 95% interval 3.3% to 10.8%; 195 claimed passing tests; place 1; 9 weeks added up.

| Week | Claimed passing | Failed check at merge, of merged |
| --- | --- | --- |
| 2026-09-28 | 103 | 5 of 83 |
| 2026-09-14 | 14 | 0 of 13 |
| 2026-09-07 | 5 | 0 of 5 |
| 2026-08-31 | 11 | 3 of 11 |
| 2026-08-17 | 12 | 0 of 10 |
| 2026-08-10 | 7 | 0 of 6 |
| 2026-07-27 | 13 | 2 of 7 |
| 2026-07-20 | 15 | 0 of 15 |
| 2026-07-06 | 15 | 0 of 15 |

**Reply.** [Reply for claude-bot](https://github.com/drexthealpha/Knos/issues/new?template=vendor-reply.yml&title=Reply+for+claude-bot&agent=claude-bot): printed here word for word.

No reply yet.

**Disputes.** [Dispute this row](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+claude-bot%2C+week+of+2026-09-28&agent=claude-bot&week=2026-09-28). Open: 0; closed: 0.

**Record.** [claude-bot's supplier record](https://drexthealpha.github.io/Knos/#record=claude-bot): grey until work is accepted under a funded order.

## codex

**Row.** 3 of 44 merged had a failed check: 6.8%, 95% interval 2.4% to 18.2%; 52 claimed passing tests; place 2 (overlaps the one above); 13 weeks added up.

| Week | Claimed passing | Failed check at merge, of merged |
| --- | --- | --- |
| 2026-09-28 | 2 | 0 of 2 |
| 2026-09-21 | 0 | not finished |
| 2026-09-14 | 7 | 0 of 7 |
| 2026-09-07 | 10 | 0 of 9 |
| 2026-08-31 | 13 | 2 of 8 |
| 2026-08-17 | 2 | 0 of 2 |
| 2026-08-10 | 1 | 0 of 1 |
| 2026-08-03 | 1 | 0 of 1 |
| 2026-07-27 | 3 | 0 of 2 |
| 2026-07-20 | 7 | 0 of 7 |
| 2026-07-13 | 3 | 1 of 3 |
| 2026-07-06 | 2 | 0 of 2 |
| 2026-06-29 | 1 | 0 of 0 |

**Reply.** [Reply for codex](https://github.com/drexthealpha/Knos/issues/new?template=vendor-reply.yml&title=Reply+for+codex&agent=codex): printed here word for word.

No reply yet.

**Disputes.** [Dispute this row](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+codex%2C+week+of+2026-09-28&agent=codex&week=2026-09-28). Open: 0; closed: 0.

**Record.** [codex's supplier record](https://drexthealpha.github.io/Knos/#record=codex): grey until work is accepted under a funded order.

## claude-code

**Row.** 3 of 31 merged had a failed check: 9.7%, 95% interval 3.4% to 24.9%; 41 claimed passing tests; place 3 (overlaps the one above); 9 weeks added up.

| Week | Claimed passing | Failed check at merge, of merged |
| --- | --- | --- |
| 2026-09-28 | 14 | 2 of 10 |
| 2026-09-14 | 6 | 0 of 5 |
| 2026-09-07 | 2 | 0 of 1 |
| 2026-08-31 | 6 | 1 of 5 |
| 2026-08-17 | 3 | 0 of 3 |
| 2026-08-10 | 4 | 0 of 3 |
| 2026-07-27 | 1 | 0 of 1 |
| 2026-07-20 | 4 | 0 of 3 |
| 2026-07-06 | 1 | not finished |

**Reply.** [Reply for claude-code](https://github.com/drexthealpha/Knos/issues/new?template=vendor-reply.yml&title=Reply+for+claude-code&agent=claude-code): printed here word for word.

No reply yet.

**Disputes.** [Dispute this row](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+claude-code%2C+week+of+2026-09-28&agent=claude-code&week=2026-09-28). Open: 0; closed: 0.

**Record.** [claude-code's supplier record](https://drexthealpha.github.io/Knos/#record=claude-code): grey until work is accepted under a funded order.

## copilot

**Row.** 22 of 80 merged had a failed check: 27.5%, 95% interval 18.9% to 38.1%; 132 claimed passing tests; place 4 (overlaps the one above); 10 weeks added up.

| Week | Claimed passing | Failed check at merge, of merged |
| --- | --- | --- |
| 2026-09-28 | 23 | 4 of 17 |
| 2026-09-21 | 39 | 4 of 22 |
| 2026-09-14 | 7 | 3 of 7 |
| 2026-09-07 | 12 | 1 of 7 |
| 2026-08-31 | 5 | 2 of 2 |
| 2026-08-17 | 13 | 3 of 10 |
| 2026-08-10 | 12 | 3 of 5 |
| 2026-07-27 | 4 | 1 of 3 |
| 2026-07-20 | 6 | 1 of 4 |
| 2026-07-06 | 11 | 0 of 3 |

**Reply.** [Reply for copilot](https://github.com/drexthealpha/Knos/issues/new?template=vendor-reply.yml&title=Reply+for+copilot&agent=copilot): printed here word for word.

No reply yet.

**Disputes.** [Dispute this row](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+copilot%2C+week+of+2026-09-28&agent=copilot&week=2026-09-28). Open: 0; closed: 0.

**Record.** [copilot's supplier record](https://drexthealpha.github.io/Knos/#record=copilot): grey until work is accepted under a funded order.

## devin

**Row.** 56 of 107 merged had a failed check: 52.3%, 95% interval 43.0% to 61.6%; 148 claimed passing tests; place 5; 9 weeks added up.

| Week | Claimed passing | Failed check at merge, of merged |
| --- | --- | --- |
| 2026-09-28 | 75 | 51 of 68 |
| 2026-09-14 | 5 | 0 of 2 |
| 2026-09-07 | 11 | 1 of 8 |
| 2026-08-31 | 11 | 1 of 10 |
| 2026-08-17 | 12 | 0 of 6 |
| 2026-08-10 | 7 | 1 of 5 |
| 2026-07-27 | 9 | 0 of 2 |
| 2026-07-20 | 14 | 2 of 4 |
| 2026-07-06 | 4 | 0 of 2 |

**Reply.** [Reply for devin](https://github.com/drexthealpha/Knos/issues/new?template=vendor-reply.yml&title=Reply+for+devin&agent=devin): printed here word for word.

No reply yet.

**Disputes.** [Dispute this row](https://github.com/drexthealpha/Knos/issues/new?template=dispute-index-row.yml&title=Dispute+a+row%3A+devin%2C+week+of+2026-09-28&agent=devin&week=2026-09-28). Open: 0; closed: 0.

**Record.** [devin's supplier record](https://drexthealpha.github.io/Knos/#record=devin): grey until work is accepted under a funded order.
