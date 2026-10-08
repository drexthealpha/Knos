# When the count is wrong

The neutral meter can be wrong. This page lists the ways, and for each one who notices, what evidence exists, what
the software does about it, and what it does not do.

**Read this first.** This page describes mechanisms. It is not a contract and it is not legal advice. Today there is:

- **no legal entity.** Nothing can sign a contract, send an invoice or be sued as Knos ([DISCLOSURE.md](DISCLOSURE.md));
- **no warranty.** The software is offered as it is, under its licence. Nobody promises that a verdict is right;
- **no service commitment.** No uptime, no response time, no support hours, for the relay, the site or anything else;
- **no data-processing terms.** No agreement covers personal data, and none can be signed ([PRIVACY.md](PRIVACY.md));
- **no insurance, no indemnity, no refund from Knos.** Knos holds nobody's money and returns nobody's loss.

So when the count is wrong, the loss stays where the mechanisms below leave it. Nobody makes it good. Money on
devnet is test USDC, which is why this is acceptable today and would not be with real money
([MAINNET.md](MAINNET.md)).

## The kinds of wrong

| What went wrong | Who notices | What evidence exists | What the software does | What it does not do |
|---|---|---|---|---|
| **A judge accepted bad work** | the buyer, later: a revert, a failing build, an audit | the signed token (which workflow, which commit, which terms hash), the run's log, the order's log lines on chain | inside the warranty, a signed revert of the paid merge returns the holdback to the funder. In the meter, either side issues a `verdict` or `withdrawn` correction, anchored in the next batch and netted in the statement. A quorum, chosen at funding, asks two or three evaluators with different owners | return what was already paid. Outside the warranty, or with no holdback, nothing comes back. No one judges whether the work was good: the checks the buyer named did |
| **A judge rejected good work** | the supplier, at once: the verdict and its reasons are posted | the verdict with its reason codes, the commit, the terms hash, the run's log | `/knos appeal <reason>`: the verdict becomes disputed and the evaluator the terms name runs the work again; an overturned rejection can be paid ([DISPUTES.md](DISPUTES.md)). An appeal costs the supplier nothing | pay after the order's deadline. An appeal that ends too late, or one no evaluator hears, pays nothing: the money goes back to the funder. Nothing compensates the supplier for the delay |
| **Insufficient evidence** (a run could not tell) | both: the verdict is its own word, never read as a rejection or an acceptance | which check or file could not be read, by reason code | counts nothing and bills nothing. The work can be judged again at no cost; the supplier can appeal it | decide. A check that stays unreadable until the deadline leaves the work unpaid |
| **A duplicate** (one deliverable counted twice) | whoever reconciles: `knos meter reconcile` lists entries made more than once, per side | the evaluation's id in both batches; the deliverable's id, which a retry shares | on chain, a token is used once and an order pays once. In the meter, a `duplicate` correction is anchored in the next batch and the statement nets it; an accepted deliverable is billed once | undo a batch that was already anchored: the program's counters only go up, so the repeat stays on chain and is corrected beside it. A duplicate nobody reconciles is never found |
| **An issuer's signing key is compromised** | the issuer, or anyone watching its published keys | the key's id in every token it signed | the guardian revokes the key, for ever; a token under a revoked key counts nothing from then on. A new key waits a day and needs the guardian's approval | take back a payment the key already made. Tokens are not re-examined after the fact. If the guardian does not act, nothing revokes the key before it expires |
| **A relay outage past a deadline** | the supplier: the token was signed and nothing was paid | the token itself, posted as a comment, with its signing time | a token is not a secret: anyone can carry it with `knos relay`, and a repository can hold its own relay key | extend a deadline. The program refuses a token presented after the deadline, whoever was at fault, and the money goes back to the funder. Proof that the token existed in time changes nothing on chain |
| **A defect in a Knos program** | anyone: the source and the deployed bytes are public | the program's hash at its public id, the build that produced it, the transactions it executed ([PROVENANCE.md](PROVENANCE.md)) | the guardian can refuse new funding for 7 days at a time. A fix is an upgrade, public for 48 hours before it can run. Refunds and withdrawals do not read the pause | repair what the defect already moved. No fund covers a loss, and no upgrade reverses a transaction. No outside firm has reviewed the programs ([ASSURANCE.md](ASSURANCE.md)) |

Two more, because they are the ones a careful reader asks next:

- **GitHub is wrong.** The count rests on GitHub's signature over a workflow run, and on GitHub's record of checks.
  If GitHub signs a false statement or loses a record, Knos cannot tell and does nothing. That trust is the design,
  and it is stated in [SECURITY.md](SECURITY.md).
- **The terms were wrong.** A buyer who names a check that proves little gets that check enforced exactly. The
  software holds the two sides to the terms; it does not say the terms were wise. `knos terms propose` drafts terms
  from what a repository's own checks did on its recent merges, and says where each line came from, so a weak line
  is at least visible ([TERMS.md](TERMS.md)).

## What is recorded when a count is corrected

A correction never rewrites anything. Each kind leaves the first record in place and adds a second one beside it:

| Correction | Where it is recorded | Who can issue it |
|---|---|---|
| an appeal, and how it ended | the appeal's record (the supplier's copy), the repository's memory, the reply on the pull request | the supplier opens it; the evaluator the terms name ends it |
| a `duplicate`, `verdict` or `withdrawn` line | the ledger, under its own leaf in the next batch's tree, so the root GitHub signs for that batch anchors it | the buyer or the seller of that ledger, each under their own id |
| a revert inside the warranty | the program's log: the holdback returned, to whom, on which signed commit | anyone, when the order allows a neutral run, with a token the pinned workflow signs only for a real revert |
| a revoked key | the key's account in the verifier program: revoked, with no instruction that clears it | the guardian |

A month's statement shows every disputed, duplicate and insufficient-evidence line as its own state, so a reader
of the statement sees that a number was contested and how it stands ([FINANCE.md](FINANCE.md)).

## Where the loss falls today

Stated without softening, by case:

- Bad work accepted and paid, no holdback: **the buyer** bears it.
- Good work rejected, the appeal late or unheard: **the supplier** bears it.
- A token signed in time and carried late: **the supplier** bears it.
- A payment under a key later found compromised: **whoever funded the order** bears it.
- A defect in a program: **whoever's money it moved** bears it.
- In no case does Knos, or any person behind it, bear it. There is nobody to claim against.

Knos's fee follows accepted value, so Knos gains from an acceptance, wrong or right. It cannot cause one: no key of
Knos's signs a verdict, and its fee account can only receive fees and lower a rate. [DISPUTES.md](DISPUTES.md),
"Knos is paid on acceptance, and does not decide it", has the five rules and the test that checks them.

## What an accountable operator would have to sign for

None of this exists. It is the list a buyer's legal and finance teams would ask of whoever runs the meter for real
money:

1. **A named contracting entity,** with an address and a jurisdiction, that can be sued.
2. **Terms of service** that say what the service is, with a limit of liability stated as an amount.
3. **A liability position for each row of the table above:** which errors the operator makes good, up to what
   amount, and which stay with the parties.
4. **A service commitment:** availability of the relay and the judge, a time to respond to an incident, and a
   remedy when it is missed. Above all, what the operator owes when its own outage makes a token late.
5. **A data-processing agreement,** a list of subprocessors, retention periods and a way to answer a deletion
   request, given that an on-chain record cannot be deleted.
6. **A dispute procedure with a named last resort:** who decides when the evaluator the terms name does not
   answer, within what time, and under which law.
7. **Control of the upgrade and guardian keys by people who answer for them:** independent holders, a tested
   succession, and notice of every upgrade ([GOVERNANCE.md](GOVERNANCE.md)).
8. **An outside security review** of the programs and the judge, with its report published.
9. **Licensed handling of real money:** legal advice on escrow and money transmission, and a regulated partner
   where the law asks for one ([REGULATION.md](REGULATION.md)).
10. **Insurance** for errors and for loss of funds, or a stated reason for having none.
11. **Support with a named owner:** who answers a supplier's finance operator about an unpaid, accepted invoice.

Until an operator signs for these, the honest description of Knos is a set of public programs and tools that two
parties may choose to use between themselves, at their own risk.
