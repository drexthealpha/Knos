# Acceptance checks for issue 21: Check a number with the Luhn rule

Test USDC, no monetary value. Written by `scripts/task_board.py` of drexthealpha/Knos from `tasks/luhn/` there.

`blackbox.py` is the judge. It runs `python3 tasks/luhn.py` in the pull request's tree with one input on standard input, for each of
the 25 recorded inputs of `cases.json` and then for inputs `gen.py` makes from a seed drawn at that moment, and
compares what the command prints with what `reference.py` answers (trailing spaces and blank lines at the end are
ignored). Exit 0 means every case agrees. A failure names the seed, so the same inputs can be made again.

It is black-box: the pull request's code runs as a separate process and the judge never loads it. A pull request that
changes anything under `.knos/` is refused before any of this runs.

What it does not do: `reference.py` is here, in a public repository, so a pull request can copy it. That is accepted for
test money. The fresh inputs stop an answer table, not a copy.
