# Outcomes that are not a merged pull request

Three orders whose deliverable is not code to merge, each as a complete bundle the existing judge runs:

| folder | the deliverable | what the black-box suite does |
|---|---|---|
| [data-labelling](data-labelling/) | `labels.csv`, a labelled dataset | scores it on gold items that were never shown |
| [data-transformation](data-transformation/) | `transform.sql` | runs it on 40 seeded input tables and checks invariants to the cent |
| [reproducible-research](reproducible-research/) | `analysis.py` and the number it is said to give | runs it again, then moves the input and requires the number to move |

Each folder has the same parts:

    README.md              what the buyer wrote
    terms.json             the terms in one sentence, the terms as funded, their hash
    evaluations.jsonl      the two lines this order adds to the meter's ledger (accepted, rejected)
    base/                  the buyer's repository when the order is funded: a starting point that fails
    base/.knos/acceptance/1/   the black-box suite: what is paid on (its hash is `accept` in terms.json)
    base/.knos/acceptance/2/   a simple check that only looks at the examples the seller can see; kept to show what it lets through
    solution/              an honest submission, laid over base/
    cheats/<name>/         a submission that passes the naive check without doing the work

Run one through the judge, from `examples/outcomes/` with Knos installed (`pip install knos`). This is the command
the pinned workflow runs:

    cp -r data-labelling/base work-base && cp -r data-labelling/base work-pr && cp -r data-labelling/solution/. work-pr/
    knos proof judge --base work-base --pr work-pr --issue 1     # the black-box suite
    knos proof judge --base work-base --pr work-pr --issue 2     # the naive check

`tests/test_outcomes.py` does that for every submission: the honest one is accepted by both bundles, the cheating one
is accepted by bundle 2 and refused by bundle 1. `python examples/outcomes/evaluation.py` prints each example's terms
and ledger lines. Standard library only; nothing is random at judging time, so a rerun gives the same verdict.

A real order would hold one bundle, the black-box one. Bundle 2 sits in the same repository here only so that the
difference can be run. [docs/reference/OUTCOMES.md](../../docs/reference/OUTCOMES.md) says what each suite cannot check.

A fourth folder is of another kind: [support-resolution](support-resolution/) has no suite and no submission. Its
outcome is a support ticket resolved, judged from the ticket's own record under terms, on made-up tickets
(`python scripts/outcome_support.py evaluate`).
