# The playground's tasks. Test USDC, no monetary value.

24 small programming tasks that [`scripts/task_board.py`](../scripts/task_board.py) opens as funded issues in
[drexthealpha/knos-playground](https://github.com/drexthealpha/knos-playground). Each pays 2 to 5 test USDC on Solana
devnet, which is worth nothing. [docs/PLAYGROUND.md](../docs/PLAYGROUND.md) is what a stranger reads.

One folder for one task:

| File | What it is |
|---|---|
| `task.json` | `title`; `statement` (its first line is "Test USDC, no monetary value."); `file` and `run` (the one file a solution edits and the command that runs it); `starting_files`; `public` (the examples a stranger sees, input and output); `hidden`, `seed` (the generator of the cases that decide, and its seed); `amount` (millionths of test USDC, 2 to 5 whole ones); `deadline_days`; `labels` (`knos-funded`, `good first issue`, `help wanted`); `reference`; `wrong` |
| `start.py` | the starting file: it prints what it read |
| `reference.py` | a solution. The judge answers fresh inputs with it |
| `gen.py` | `inputs(rng)`: input lines from a seeded `random.Random`, edge cases first |
| `wrong_1.py` to `wrong_3.py` | plausible wrong solutions. The test suite checks that each fails |

A solution reads one input on standard input and prints one answer. The judge is black-box: it runs the file as a
separate process on the recorded cases and on inputs made when it runs, and compares what is printed with the
reference's answer. The reference is public here, so a pull request can copy it: that is accepted for test money.

[`tests/test_task_board.py`](../tests/test_task_board.py) holds, for every task: the reference passes, each of the three
wrong solutions fails, the starting file fails, and a pull request that touches the checks is refused.

## Take one as an agent

`knos task list` reads the board the site publishes
([`tasks.json`](https://drexthealpha.github.io/Knos/tasks.json)): each task with its amount, its acceptance terms and
how payment happens. `knos task take <task> --address <address> --login <you> --branch <branch>` returns the pull
request link that already says `Closes #N` and the `/knos address` comment; it sends nothing. `knos task submit ...
--send` has `gh` post both as you. Over MCP the same three steps are `tasks_open`, `task_show` and `task_take`
([`src/knos/tasks.py`](../src/knos/tasks.py); [`tests/test_tasks.py`](../tests/test_tasks.py) acts the whole path out
against the tests' own GitHub, chain and relay, to the payment).

### A held payment

A merge that passes with no address and no bound wallet is
held for the author's account. The board lists it under `held`, the playground page shows it, and the instruction is
one comment by the payee on the pull request: `/knos address <your Solana address>`.

### Why a merged pull request was not paid

`knos task why owner/repo#N --pull M` (or
`python scripts/task_board.py why ...`) reads the order from the chain and says one sentence and one fix. The case that
happened: an order names, when it is funded, the workflows whose signed run may pay it, and one merged pull request in
`drexthealpha/knos-e2e` was not paid because its order had been funded through a staging copy of the workflows. A
maintainer's `/knos tip` on the merged pull request then put the amount in escrow for the author, where it is held
until the author says where it goes. The board now reads the playground's own
workflow files before it funds anything and funds nothing unless they call the public pinned workflows.

## Ten tasks that are not code puzzles

Each turns one of the outside-use counts from zero to one, and only when the account that does it is not one of
Knos's own. The files are [`tasks/outside/`](outside/); `knos task kinds` prints them.

| Task | What you do | Evidence a machine checks | Counter |
|---|---|---|---|
| `reproduce` | run the `knos reproduce` workflow in your own copy of the template and file the report | a file under `reproductions/` that GitHub signed for your account ([REPRODUCE.md](../docs/REPRODUCE.md)) | reproductions |
| `shadow` | run `knos shadow` on agent pull requests of a repository you own and publish the statement | a published statement whose repository's owner is your account ([SHADOW.md](../docs/SHADOW.md)) | shadow counts published |
| `fund` | take test USDC from the faucet and fund an issue in a repository you own | a funded job on devnet that `scripts/outsiders.py` reads as an outside funder ([FAUCET.md](../docs/FAUCET.md)) | outside funders |
| `install` | install the check in a repository you own and let it finish once | the default branch calls the public pinned check, and one finished run ([INSTALL.md](../docs/INSTALL.md)) | outside repositories |
| `judge` | host a judge from the template `examples/host_a_judge` | one GitHub-signed attestation run in a repository you own | judges hosted outside |
| `compose` | build a program on the published crate `knos-oidc-interface = "0.3.14"` ([reader template](../examples/reader_template)) and read the verifier from it on devnet | one devnet transaction of your program that reads a token `knos-oidc` verified | outside programs reading the verifier |
| `gate` | put a program of yours behind the upgrade gate ([GATE.md](../docs/GATE.md)) | your gate's build record on devnet, and `adopt.py check` exiting 0 | programs behind the gate outside |
| `keyholder` | offer a key through the key holder issue ([KEYHOLDER.md](../docs/KEYHOLDER.md)) | an issue your account opened from that template, naming a public key | key offers (never holders until seated) |
| `tamper` | write a submission meant to fool the judge on a task ([TAMPER.md](../docs/TAMPER.md)) | a judge verdict of accepted on work that does not do what the task asks; refused is not paid | cheats written outside |
| `witness` | run one transaction start to end in a repository of yours ([examples/witnessed](../examples/witnessed)) | `witness.json`: funding, a refused run, the payment, a refused replay, two statements with one hash, the verifier's result | witnessed transactions |

Every one pays 5 test USDC from a task Knos funded itself, and a count that comes from one is shown with those words:
"on tasks Knos funded itself". `python scripts/task_board.py open --kinds` opens each as a funded issue in the playground
that a maintainer's merge pays: the pull request adds one file, `outside/<kind>/<login>.json`, with the evidence.
None is an offer of work. `tasks.accepts` checks the evidence and `outsiders.task_counts` decides who is outside;
neither has been met by anyone yet. The site's `outsiders.json` publishes each counter (`task_counts`), read from the
evidence files merged into the playground; a file counts only for the account its name says.

The text of each is `KINDS` in [`src/knos/tasks.py`](../src/knos/tasks.py), and a test holds the files to it. Each file states what to
do, the `evidence`, the fields that evidence `needs`, and the one `counter` it can move
([`scripts/own_github_ids.json`](../scripts/own_github_ids.json) says what is Knos's own).
