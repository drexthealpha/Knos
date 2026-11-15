# The playground's tasks. Test USDC, no monetary value.

24 small programming tasks. [`scripts/task_board.py`](../scripts/task_board.py) opens each one as a funded issue in
[drexthealpha/knos-playground](https://github.com/drexthealpha/knos-playground). Each pays 5 test USDC on Solana devnet
(Solana's test network). Test USDC is worth nothing. [docs/reference/PLAYGROUND.md](../docs/reference/PLAYGROUND.md) is what a stranger
reads.

One folder for one task:

| File | What it is |
|---|---|
| `task.json` | the task. Fields: `title`; `statement` (first line: "Test USDC, no monetary value."); `file` and `run` (the file a solution edits and the command that runs it); `starting_files`; `public` (examples a stranger sees, input and output); `hidden` and `seed` (the generator of the deciding cases, and its seed); `amount` (millionths of test USDC: 5000000, so 5, for every task. The schema allows 2 to 5, but the escrow takes no order under 5); `deadline_days`; `labels` (`knos-funded`, `good first issue`, `help wanted`); `reference`; `wrong` |
| `start.py` | the starting file: it prints what it read |
| `reference.py` | a solution. The judge answers fresh inputs with it |
| `gen.py` | `inputs(rng)`: input lines from a seeded `random.Random`, edge cases first |
| `wrong_1.py` to `wrong_3.py` | plausible wrong solutions. The test suite checks that each fails |

A solution reads one input on standard input and prints one answer. The judge is black-box: it does not read the
code. It runs the file as a separate program on the recorded cases and on new inputs made at that moment. Then it
compares what is printed with the reference's answer. The reference is public here, so a pull request can copy it.
For test money, that is accepted.

[`tests/test_task_board.py`](../tests/test_task_board.py) checks four things for every task. The reference passes. Each
of the three wrong solutions fails. The starting file fails. A pull request that touches the checks is refused.

## Take one as an agent

`knos task list` reads the board the site publishes
([`tasks.json`](https://drexthealpha.github.io/Knos/tasks.json)). It shows each task with its amount, its acceptance
terms and how payment happens. `knos task take <task> --address <address> --login <you> --branch <branch>` returns two
things: the pull request link that already says `Closes #N`, and the `/knos address` comment. It sends nothing.
`knos task submit ... --send` has `gh` (GitHub's command line tool) post both as you. Over MCP (Model Context Protocol,
the way AI agents call tools) the same three steps are `tasks_open`, `task_show` and `task_take`
([`src/knos/tasks.py`](../src/knos/tasks.py)). [`tests/test_tasks.py`](../tests/test_tasks.py) acts out the whole
path, up to the payment, against the tests' own stand-ins for GitHub, the chain and the relay.

### A held payment

Sometimes a merge passes but the author gave no address and has no wallet linked. Then the payment is held for the
author's account. The board lists it under `held`, and the playground page shows it. To collect it, the author posts
one comment on the pull request: `/knos address <your Solana address>`.

### Why a merged pull request was not paid

`knos task why owner/repo#N --pull M` (or `python scripts/task_board.py why ...`) reads the order from the chain. It
answers in one sentence and gives one fix.

What happened once: a pull request in `drexthealpha/knos-e2e` was merged but not paid. Its order had been funded
through a test copy of the workflows, and an order only pays a signed run of the workflows it names. A maintainer then
tipped the author with `/knos tip` on the merged pull request. That put the amount in escrow (held by the program) until
the author says where it goes. The board now reads the playground's workflow files before it funds anything. It funds
nothing unless they call the public workflows, pinned to one commit.

## Ten tasks that are not code puzzles

Each asks someone outside Knos to try one part of the product and file the evidence. A finished task is counted in
the outside-use numbers only for an account that is not Knos's own. The count always carries the words "on tasks Knos
funded itself". The files are [`tasks/outside/`](outside/); `knos task kinds` prints them.

| Task | What you do | Evidence a machine checks | Counter |
|---|---|---|---|
| `reproduce` | run the `knos reproduce` workflow in your own copy of the template and file the report | a file under `reproductions/` that GitHub signed for your account ([REPRODUCE.md](../docs/reference/REPRODUCE.md)) | reproductions |
| `shadow` | run `knos shadow` on agent pull requests of a repository you own and publish the statement | a published statement whose repository's owner is your account ([SHADOW.md](../docs/reference/SHADOW.md)) | shadow counts published |
| `fund` | take test USDC from the faucet and fund an issue in a repository you own | a funded job on devnet that `scripts/outsiders.py` reads as an outside funder ([FAUCET.md](../docs/reference/FAUCET.md)) | outside funders |
| `install` | install the check in a repository you own and let it finish once | the default branch calls the public pinned check, and one finished run ([INSTALL.md](../docs/reference/INSTALL.md)) | outside repositories |
| `judge` | host a judge from the template `examples/host_a_judge` | one GitHub-signed attestation run in a repository you own | judges hosted outside |
| `compose` | build a program on the published crate `knos-oidc-interface = "0.3.14"` ([reader template](../examples/reader_template)) and read the verifier from it on devnet | one devnet transaction of your program that reads a token `knos-oidc` verified | outside programs reading the verifier |
| `gate` | put a program of yours behind the upgrade gate ([GATE.md](../docs/reference/GATE.md)) | your gate's build record on devnet, and `adopt.py check` exiting 0 | programs behind the gate outside |
| `keyholder` | offer a key through the key holder issue ([KEYHOLDER.md](../docs/reference/KEYHOLDER.md)) | an issue your account opened from that template, naming a public key | key offers (never holders until seated) |
| `tamper` | write a submission meant to fool the judge on a task ([TAMPER.md](../docs/reference/TAMPER.md)) | a judge verdict of accepted on work that does not do what the task asks; refused is not paid | cheats written outside |
| `witness` | run one transaction start to end in a repository of yours ([examples/witnessed](../examples/witnessed)) | `witness.json`: funding, a refused run, the payment, a refused replay, two statements with one hash, the verifier's result | witnessed transactions |

Each pays 5 test USDC, which has no monetary value, from a task Knos funded itself. It is a trial, not paid work.
`python scripts/task_board.py open --kinds` opens each one as a funded issue in the playground. The pull request adds
one file, `outside/<kind>/<login>.json`, holding the evidence. A maintainer checks it with `knos.tasks.accepts` and
merges, and the merge pays. `task_counts` in `scripts/outsiders.py` decides who is outside Knos. Nobody has completed one yet.
The site's `outsiders.json` shows each count (`task_counts`), read from the evidence files merged into the playground.
A file counts only for the account its name gives.

The text of each is `KINDS` in [`src/knos/tasks.py`](../src/knos/tasks.py), and a test holds the files to it. Each file states what to
do, the `evidence`, the fields that evidence `needs`, and the one `counter` it can move
([`scripts/own_github_ids.json`](../scripts/own_github_ids.json) says what is Knos's own).
