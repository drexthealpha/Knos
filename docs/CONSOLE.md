# The console: an operator's guide

The Buy page of the site (`#buy`, [`web/buyer.js`](../web/buyer.js) and [`web/console.js`](../web/console.js)) is for
the person who authorises a payment and has to defend it afterwards, and for the supplier on the other side. It is a
static page: it reads GitHub's public API, Solana devnet and this site's own files, and nothing else. It sends nothing
to Solana. Money is test USDC on devnet.

This guide says where the page answers each of the seven questions that person is asked, how many steps a governed
order takes, and what the page does not do.

## The seven questions, and where each is answered

| Question | Where on the page | What it is read from |
| --- | --- | --- |
| What did we buy, from whom, at what price? | Step 1 (the issue, the amount, the fee as an amount and as a share of the order) and step 2 (the terms in one sentence). After the fact: the statement, one line per payment with its supplier ids. | What you type; the price constants of the program; the site's statement file `audit/<owner id>.json`. |
| Which evidence establishes acceptance? | Step 4, "Accepted: the receipt, in its five parts": what the issuer authenticated, what the evaluator observed, which policy produced the verdict, who authorised the money and under which limit, what trust remains. Each line links its transaction. | The order's account and the program's log lines on devnet. The run's own log stays on GitHub. |
| Was this deliverable billed before? | Step 1, "Was this billed before?": every earlier order and payment for the same repository and issue, each with its milestone and its transactions, shown before funding. | The organisation's statement file on this site, and the issue's open orders on devnet. |
| Did the approver have authority? | Step 1, "Is this allowed?": the organisation's cap per order, what is left today and in all, the allowed repositories and who may spend, with whether this funding would pass and which rule decides. Step 4 names who funded the order. | The organisation's Balance and its side account on devnet; the funding's log line. |
| What happens on a revert or a dispute? | "What needs a person": the orders held for a payee with no wallet, in a review window, reverted or ruled on by an arbiter, cancelled, past deadline and refundable, reserved and stale, each with the one action that resolves it and who can take it. Step 4 lists the four exception paths. For a private repository, a panel in step 1 says what the supplier cannot do alone. | The statement file, each order's account on devnet, and the repository's record file for refused tokens. |
| Can finance reproduce the statement next quarter? | "The month's statement, for both sides": Export CSV and Export JSON are byte for byte what `knos audit export` prints for the same owner and month, and the head is the one hash both sides compare. A meter ledger file dropped on the card adds its three numbers. | The statement file; the ledger file you drop, read in the browser and sent nowhere. |
| Who answers when the service fails? | Step 4, "Who answers if this fails". | Nothing: it is a statement. Today the founder alone answers. There is no support contract, no on-call team and no service-level agreement. A refund after the deadline, the release of a holdback and the settling of a held payment can each be sent by anyone, so the money does not wait on that person. |

## The fee, before funding

The page never shows the rate alone. Beside the amount it says the fee as an amount and as a share of the order, and
under 20 test USDC it warns: the fee is never less than 0.40, so an order of 5 costs 8.00%. Small purchases are
cheaper pooled into one order with milestones, or bought at a standing rate. The table under the amount is the price
book's:

| Order | Fee | Fee as a share |
| ---: | ---: | ---: |
| 5 | 0.40 | 8.00% |
| 20 | 0.50 | 2.50% |
| 1,000 | 25 | 2.50% |
| 5,000 | 65 | 1.30% |
| 50,000 | 515 | 1.03% |

`tests/web/buyer.mjs` reads these five rows off the page. On devnet the fee is test money.

## A governed order, counted

A governed order is one funded by comment from the organisation's Balance, after the page has said that the budget
lets it through and that the issue was not billed before. From an empty page it takes **3 fields and 2 clicks**:

1. Paste the issue's address. The budget and the earlier billing appear by themselves.
2. Choose the terms from a template.
3. Write the amount.
4. Click "Copy the comment".
5. Click "Open the issue".

Then, on GitHub: paste, and press Comment. No YAML is edited and no terminal is opened. The number is counted by
`tests/web/buyer.mjs` in headless Chromium against mocked chain data, and `tests/test_site_buyer.py` fails if this
page states another. Leaving the template as it is makes it 2 fields. Naming who will post the comment, so that the
"who may spend" rule is judged too, adds one optional field.

What the count does not include, and what was not measured:

- It is a scripted run, not a person. Nobody outside the project has been timed doing it, so there is no measured
  completion time or abandonment rate.
- The repository must already have the Knos workflow, which arrives once as a reviewed pull request from the
  [Install page](INSTALL.md).
- The organisation must already have a Balance with its limits. A wallet opens one on the site's Balance page; the
  limits of the side account (daily, total, repositories) are set with the command line today
  ([CONTROLS.md](CONTROLS.md)).

## What the page cannot tell you

- **The budget is a reading, not a reservation.** Between the reading and the comment someone else can spend. The
  program decides when the comment is carried; the page says what it would decide now, with the time it read.
- **Who may spend is judged only if you name the commenter.** With the box empty the page checks the limits and
  lists the accounts that may spend.
- **Billed before is as complete as its sources.** The statement file is rebuilt with the site; an order funded since
  then is found only if it is still open and was funded from one of the organisation's Balances or from this
  browser's passkey wallet. Private orders name no repository in public and cannot be matched.
- **Refused tokens are a count.** The site's file of a repository keeps how many payments or proofs the relay refused
  at a merge, not each one; the reason is in the relay's answer on the pull request.
- **Deadlines and reservations need devnet.** If devnet does not answer, the exceptions list says so and shows what
  the statement alone holds.
- **A policy file is not read.** The limits shown are the Balance's, which the program enforces. An organisation's
  `.knos/policy.yml` is checked by the command job when the comment runs.
- **The meter's numbers are the file's.** A dropped ledger is counted as `src/knos/ledger.py` counts it (each
  evaluation once, corrections applied, one accepted outcome per deliverable), over the whole file. The page does not
  compare it with the chain; `knos meter verify` does.

## Private repositories

When the repository is private, or the terms are the private template, step 1 shows a panel before funding. In
short: a supplier cannot settle a private order alone, because only a run of the buyer's own workflow can accept
the work; the evidence stays where the buyer controls access; and an arbiter can be named in the funding comment,
and only then. Knos has no neutral evaluator with its own access to a private repository and keeps no copy of the
evidence for the supplier. [SECURITY.md](SECURITY.md) has the full account.
