# Evidence plan (fixed 28 Oct 2026, before any run it names)

Knos's own claims, each tested against a real outcome with a control that tries to break it. Every number this plan
names is published as the script recomputes it from committed raw files, wins and losses alike. No Qloo call is made.

## 1. A clear brief before the work (IDT)

- Tasks: the 20 tasks of `bench/idt/tasks.json`, unchanged (12 code tasks, 8 brief tasks).
- Arms, each run once per task through Claude Code in print mode on the operator's subscription
  (`claude -p --output-format json --model sonnet --effort medium --tools ""`, no API key):
  1. the vague brief;
  2. the Ready brief;
  3. the control: the vague brief padded with neutral filler to the Ready brief's length in characters, so that
     length alone cannot explain a difference. The filler is the sentence "This line adds nothing to the request."
     repeated, then cut to the exact length.
- Metric: output tokens as the API returned them (thinking is billed as output), and pass or fail by the task's own
  check (its asserts on the Python, or `knos.ready.check` on a JSON brief).
- Results: the ratio of total output tokens, vague to Ready and control to Ready, each with a 95% bootstrap interval
  over tasks (10,000 resamples, `random.Random(7)`, the 2.5th and 97.5th percentiles); the pass rate of each arm;
  every task where the Ready brief lost (more output tokens than the vague brief, or a fail where the vague passed).
- Pass rule for the claim "a Ready brief costs fewer output tokens": the lower end of the vague-to-Ready interval is
  above 1, and the control-to-Ready interval is too. Otherwise the page says the claim did not hold.
- Raw files: `docs/idt/e1/runs.json` (every run) and `docs/idt/e1/summary.json`, written by
  `python scripts/idt_bench.py --arms vague,ready,control --out docs/idt/e1`.

## 2. Proof checking against altered pull requests

- Inputs: the two sample repositories this machine can run, Python (`tests/bench_tamper/sample/`) and JavaScript
  (`tests/bench_tamper/sample_node/`), each with its one unfixed bug.
- 60 new pull requests, 30 per repository, by mutation, none of which fixes the bug: 6 of each of these 5 operators.
  1. deleted test: one of the repository's own tests removed;
  2. skipped test: one test marked skipped;
  3. weakened assert: one assertion replaced by a check that always holds;
  4. renamed check: the CI job that runs the tests renamed, its tests left out;
  5. forged check name: a CI step named like the test job that runs no test and exits 0.
  The 6 variants of an operator differ in which test or which job name they touch, in a fixed order
  (`scripts/e1_mutants.py`).
- Referees: the pull request's own CI test steps ("CI green"), and Knos's referee on the funder's acceptance tests
  (`knos.judge.judge`, tests mode). A pull request is caught when the referee refuses to pay it.
- Results: caught out of 60 for each referee, per operator, and every miss by name.
- Raw file: `docs/reference/e1_mutants.json`, written by `python scripts/e1_mutants.py`.

## 3. What Qloo adds, from recordings already made (0 new calls)

Every with-and-without-Qloo result already measured is published with its date and raw file, wins and losses alike:

- the verdict changed on 14 of 20 ideas against a free-data baseline;
- the Census where-test, which Qloo lost (0.193 against 0.407);
- the taste test, which tied;
- the crowdfunding test on a public dataset of crowdfunded product launches, which showed no lift.

## 4. The pre-order flow

The count of real devnet holds and releases in the Knos record (Sibyl), split into the founder's own wallets and
others'. Nothing is counted that the record does not hold.

## Where it is shown

As numbers on the front door's proof line and on How we test Knos, each linked to this plan's commit. Published by
`python scripts/e1_publish.py`, which recomputes every number from the raw files above and fails on any difference.
