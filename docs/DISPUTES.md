# Disputes

A supplier who thinks a rejection is wrong can contest it, and nobody from Knos is needed for any step. This page says
what each party can do at each state, which clock runs, where the money is, and what happens when the evaluator the
terms name never answers. It states what the code does today (`src/knos/appeal.py`, `src/knos/flow.py`, the order
instructions of `knos_pay`), and where the code does less than the terms say, it says so.

Money on devnet is test USDC. This page describes mechanisms. It is not a contract and not legal advice
([LIABILITY.md](LIABILITY.md)).

## The path

    rejected, or insufficient evidence
        /knos appeal <reason>          the pull request's author comments it on the pull request
    disputed (open)                    who, when and why are recorded; no money moves
        the evaluator is started       the one the terms name under `dispute`
    disputed (re-running)              that evaluator runs the funded checks again, itself
    accepted                           the checks passed there: the rejection is overturned, and the order can be paid
    rejected                           they did not pass there: the rejection stands, with the reasons in words

Two orders have two evaluators, and the terms say which ([TERMS.md](TERMS.md), the `dispute` field):

- **An order decided by an acceptance suite.** The evaluator is the neutral judge: the pinned `attest.yml`, started
  in a repository whose owner is neither party. Its first job fetches the two commits and runs the funded suite
  again under another account. Its verdict ends the appeal.
- **An order paid on a merge.** There is no suite to run again: the neutral judge reads the repository's check
  results and runs nothing. The appeal is ruled by the arbiter the order named at funding. An order that named no
  arbiter has nobody to rule: the rejection stands unless both sides agree on an arbiter and fund a new order.

A re-run that could not run (the judge's machine, an image, GitHub) decides nothing. The appeal goes back to
`disputed (open)` and the evaluator is asked again.

## Who can do what, at each state

| State | Supplier (the pull request's author) | Buyer (the funder) | The evaluator the terms name | Anyone else |
|---|---|---|---|---|
| rejected, or insufficient evidence | open an appeal with one sentence of reason, at no cost; or push a new commit and be judged again | nothing is asked of them; they may cancel the order, which takes 7 days' notice | nothing yet | read the verdict and its reasons |
| disputed (open) | start the neutral judge themselves (`knos settle --neutral <pull request>`), from a repository that is not the buyer's; export the appeal's record | start the neutral judge too; they cannot close the appeal, and cannot take the money before the deadline | be started, by either side or by a third party | start the neutral judge from a repository of their own, when the order allows a neutral run |
| disputed (re-running) | wait; a second appeal of the same verdict is refused | wait | run the funded checks again and sign the verdict; or, as arbiter, rule | read the run's public log |
| accepted | be paid: the neutral judge's signed token is carried to the program by any relay (`knos settle`) | nothing can stop a token that is valid before the deadline | nothing more | carry the token (a payment tips whoever relays it) |
| rejected (the appeal ended) | open a new pull request, judged again at no cost; a second appeal of the ended one is refused | nothing | nothing more | read the reasons |
| past the order's deadline, no verdict | nothing on chain: a pay token is refused now | send the refund, as anyone can | a verdict signed now pays nothing | send the refund: the money goes back to the funder |

Only the supplier can open an appeal. An accepted verdict cannot be appealed by the supplier, because nothing was
refused. A buyer who thinks accepted work was wrong does not appeal: they use the warranty, below.

## The clocks

Each clock is in the terms or in the order, and none is kept by Knos.

| Clock | Where it is fixed | What the code enforces today |
|---|---|---|
| time to appeal | terms 3, `dispute.within_days` | for an order funded under terms 3, `/knos appeal` refuses a late appeal with the sentence (`knos.terms3.appeal_open`, counted from the rejection the judge's memory holds); an order with no terms 3 has no such window |
| the order's deadline | the order, at funding (terms 3 `deadline.days`) | the program refuses a pay token after it, and anyone can then send the refund |
| a cancel's notice | the program: 7 days | a funder's cancel moves the deadline to at most 7 days away; a valid token inside the notice still pays |
| the warranty | the order, at funding (terms 3 `window`) | the holdback stays in the order until it ends; a signed revert inside it returns the holdback to the funder |

The practical consequence: an appeal must be opened, re-run and paid before the order's deadline. An appeal opened
on the last day can be right and still pay nothing, because the token would arrive late. The supplier's protection
is to appeal early and to start the neutral judge themselves, which needs nobody's permission.

## Where the money is

- **While an appeal is open** the money stays in the order, in the program's account. An appeal moves nothing. The
  buyer cannot withdraw it before the deadline; they can give notice of cancellation, which takes 7 days.
- **When the appeal ends accepted** the evaluator's signed token pays the supplier the amount. The fee is the
  funder's, on top of the amount.
- **When it ends rejected** the money stays in the order for the next pull request, until the deadline.
- **If the order was already paid** the appeal is about the record only and moves nothing.
- **If the order was already refunded** an overturned verdict pays nothing. A new order would have to be funded.
- **An appeal costs the supplier nothing,** whatever its outcome. Its re-run is not billed to them.

## When the named evaluator never answers

Nothing forces an evaluator to run, and nothing replaces one that does not.

- **The neutral judge** is a workflow file, not a person. Either party, or anyone, can start it in a repository of
  their own, when the order allows a neutral run. It "never answers" only if nobody starts it, or if GitHub or the
  pinned workflow repository cannot be reached. An order funded with `neutral off` can be judged only from its own
  repository or its named judge's, so there the buyer can decline to start it.
- **An arbiter** is one GitHub account. They can rule wrongly, or not at all.
- **In both cases the on-chain rule decides:** an order with no payment by its deadline goes back to its funder,
  amount and fee. Anyone can send that refund. So the default when no evaluator answers is that the buyer keeps the
  money and the supplier's work is unpaid. The terms cannot say otherwise: `dispute.no_answer` has one permitted
  value, `refund-at-deadline`, and `knos terms verify` refuses any other.

This favours the buyer, and the terms say so in their own words. A supplier who does not accept that asks for terms
with an acceptance suite and a neutral run allowed, before taking the work.

## The buyer's side: accepted work that was wrong

A buyer cannot appeal an acceptance. What they have is fixed at funding:

- **A holdback and a warranty.** A share of the payment stays in the order for the warranty. If the paid change is
  reverted on the default branch in that time, a signed revert returns the holdback to the funder. What was already
  paid stays paid.
- **A quorum.** Two or three evaluators with different owners must accept the same work before anything is paid.
- **A correction in the count.** For work that is counted by the meter and not paid on chain, either side issues a
  correction (`duplicate`, `verdict` or `withdrawn`) that rides in the next batch and is netted in the statement
  ([METER.md](METER.md)).

## What each party can export

| Who | What | How |
|---|---|---|
| supplier | the appeal's record: who, when, why, the ids of the deliverable and the evaluation, the terms' hash, every step | `knos appeal "<reason>" ... --out FILE`, or the reply on the pull request |
| supplier | their record in a repository: accepted, rejected, appealed, overturned | `knos appeal --record <login> --repo <owner/name>` |
| either | the terms the order was funded on, and which published version they are | `knos terms verify <file or hash>` |
| either | the neutral judge's verdict and its run log | the run's page on GitHub; `verdict.json` in its artifacts |
| either | a month's statement with every disputed line marked | `knos statement make`, then `knos statement export` ([FINANCE.md](FINANCE.md)) |
| anyone | what the order held, paid and returned | the order's account and the program's log lines on Solana devnet |

## What is not built

- The comment handler reads the terms 3 file an order was funded under (the version whose hash the order's terms
  carry) and refuses an appeal outside `dispute.within_days`. `knos appeal open` on the command line does not check
  the window, and a private order has no terms 3 file to read.
- There is no hosted queue of disputes, no notification to the evaluator, and no service commitment on how fast an
  evaluator answers.
- A payment made without a merge (`auto`) cannot be challenged by a neutral run today ([SECURITY.md](SECURITY.md),
  section 19).
- No dispute has been opened by an outside supplier. Every appeal so far is a test.
