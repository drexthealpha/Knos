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
