# Outcomes other than a merged pull request

Each domain needs its own acceptance model; Knos supplies the fixed terms, the signed run and the count, not the model.

An order pays, or the meter counts, when a pinned suite passes on an artifact. Nothing in that sentence says "pull
request". What the artifact is, and what a suite must do to deserve the word "accepted", differs for every kind of
work, and somebody who knows the work has to write it. This page shows three such models that run in this repository
and one that is not built, with the reason.

| Outcome | Artifact | What the suite checks | What it cannot check | Status |
|---|---|---|---|---|
| [Data labelling](../examples/outcomes/data-labelling/) | `labels.csv`: a label for each of 400 items | Schema; accuracy at least 0.90 on 120 gold items never shown; recall at least 0.80 for each class; the 40 visible examples no more than 0.10 above the gold ones (copied answers) | The 280 items outside both samples, except by inference; whether the gold labels are right; secrecy of the gold file from a labeller who can read the repository | Example runs here; never used by a customer |
| [Data transformation](../examples/outcomes/data-transformation/) | `transform.sql` | On 40 input tables made from fixed seeds: schema, one row per key, every input customer and charge counted once, totals equal to the input's to the cent, each row equal to a reference | Inputs shaped unlike the generator's; speed at production volume; other database engines | Example runs here; never used by a customer |
| [Reproducible research](../examples/outcomes/reproducible-research/) | `analysis.py` and `RESULT.json`, the number it is said to give | Run again in the sandbox with the order's seed: the number matches within 0.000001; a second run agrees; when the input is moved by a known amount the number moves by it (a pasted number does not) | Whether the method answers the question; whether the data are real; whether the seed or the method was chosen after looking | Example runs here; never used by a customer |
| Support-ticket resolution | none that Knos can read | nothing | see below | Not built |

`tests/test_outcomes.py` puts every submission of the three examples through `knos proof judge`. Each example holds
the black-box suite and, beside it, a naive check that looks only at what the supplier was shown. The honest submission
is accepted by both. The cheating submission (copied visible labels; the worked example's answer written down; a
result pasted into the script) is accepted by the naive check and refused by the black-box suite.

## What is the same in every domain

- **The terms are fixed before the work.** Each example's `terms.json` holds the hash of its suite (`accept`). Change a
  threshold, a gold label or a seed and the hash changes, so the suite funded is the suite that judges.
- **The run is the judge's.** The suite runs outside the submission's tree and reaches it only through `$KNOS_RUN`,
  in the sandbox: a file is read out, a script is run, a SQL file is executed, and only the output is compared. The
  suite's own data (gold labels, the reference, the trial's rows) are taken out of the tree first.
- **The count is the meter's.** An evaluation is identified by four fields whatever was delivered, and is billed once:

      id = sha256(order || artifact digest || policy version || milestone)

  Each example's `evaluations.jsonl` holds two lines in the ledger format of [METER.md](METER.md), one for the honest
  submission (accepted) and one for the cheating one (rejected). They share the order, the policy (the hash of the
  terms) and the milestone, and differ in the artifact, so they are two evaluations. Judging the same artifact again
  under the same policy is the same evaluation and is not counted twice.

## What is different, and stays the buyer's work

The thresholds, the gold set, the invariants, the perturbation: these are the acceptance model, and they are the part
with judgment in it. Knos does not know that 0.90 is the right accuracy for a labelling job or that a shifted treatment
arm is the right test of a computed effect. `knos.judge.black_box` checks only that a bundle is built so that the
submission cannot reach the verdict except through its output. A suite can be black-box and still be a poor model of
"done"; the fourth column of the table is each example's own list of that.

One limit of the count is the program's and is not changed here: the meter's artifact field holds 40 characters, the
size of a commit id. A deliverable that is a file is judged in a commit, and the commit is the artifact. The examples
are folders, not commits, so their ledger lines carry the first 40 hex characters of a hash of the submission's files.

## Support-ticket resolution: not built

Vendors of support agents bill per resolution, and each counts its own. A neutral count would be worth having. A
"resolved" webhook is not an acceptance model, for three reasons.

**Who says it is resolved.** The webhook is sent by the system that is being paid, or by a help desk configured by
one of the two parties. Knos would authenticate the run that received the event and nothing about the event itself:
[ADAPTERS.md](ADAPTERS.md) draws that line for every external source. A count of unauthenticated events is the
vendor's count with a signature on the envelope.

**Resolved is a state, not a fact.** Tickets reopen. A customer who got a wrong answer and gave up looks the same in
the event stream as one who was helped. One vendor's published definition counts a resolution when the customer
confirms, or when the customer "exits the conversation without requesting further assistance", and takes the
resolution back if the customer later returns to the same conversation
([Intercom, "Fin resolutions"](https://www.intercom.com/help/en/articles/8205718-fin-resolutions), read 5 October
2026). So the number that is billed is settled only after a window, and a reopen rate is part of the outcome.

**The customer's confirmation is the evidence, and it is not in the webhook.** The person who can say the problem is
solved is a third party to the order. Their confirmation, or their silence over a stated period, has to be read from
where it is recorded, not from a message that says it happened.

What a real model would need:

1. **The system of record's own word.** A pinned workflow that reads the ticket from the help desk's API with the
   buyer's credential: its state, its history of reopens, who closed it, whether the customer answered. Or an event
   signed by the help desk itself (not by the agent vendor) with a public key the buyer pins. The trackers that
   [ADAPTERS.md](ADAPTERS.md) covers sign their webhooks with a shared secret, which a program on a public chain
   cannot check, so today only the first route is open: re-read the API, believe nothing that was sent.
2. **A stated definition in the terms.** Which states count, who may set them, and whether a confirmation from the
   customer is required or silence is enough. That is a field of the terms, hashed like a suite.
3. **A reopen window as a warranty.** The evaluation is made when the window closes, or an accepted outcome is
   reversed by a later evaluation of the same deliverable if the ticket reopens inside it. The meter today has no
   reversal: an accepted evaluation stays accepted. So the first form (judge after the window) is the one that fits
   without a program change.
4. **A sample a person reads.** Whether an answer was right is not in any ticket state. A buyer who pays per
   resolution audits a sample, and the terms should say how large and what follows from a failed one.

None of this is built. There is no help-desk adapter, no signed-event verifier for one, no reopen window, and no
example under `examples/outcomes/` for it, because an example driven by a made-up webhook would show the thing this
section says not to trust.
