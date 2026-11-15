# Acceptance checks for issue 7

Made by `knos accept init` from a reference implementation: 5 inputs (given, seed none) and the answer the reference
gave to each, in `cases.json`. `blackbox.py` is the judge. It runs `python3 words.py` in the pull request's tree for every input,
with the input on standard input, and compares what it prints with the recorded answer (trailing spaces and blank lines at
the end are ignored). Exit 0 means every case agrees.

It is black-box: the pull request's code runs as a separate process, and the judge never loads it, so nothing that code
does can change the verdict except printing the right answer. That is what lets Knos pay on this check alone, without a
merge, when this folder is on the default branch before the bounty is funded: `/knos fund <amount>` on issue 7.

What it does not do: the cases are in this repository, so an implementation can answer exactly them from a table. More
cases make that more work, not impossible. A check that generates its inputs when it runs and compares them with a
reference at that time cannot be answered from a table: write that as `blackbox.py` yourself if the bounty is worth it
(Knos's docs/TAMPER.md measures the difference).
