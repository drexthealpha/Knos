# One transaction, witnessed by you

Test USDC, no monetary value. You need a GitHub account, `gh` logged in, `git`, and `pip install knos`.

1. `python examples/witnessed/witness.py plan --login YOU` lists the 13 steps. It sends nothing.
2. `python examples/witnessed/witness.py run --login YOU` does them in a repository of yours, made from `drexthealpha/knos-task`.
   Run again, it uses that repository: its caller workflows are brought to the template's, and the work goes on a new branch.
3. It funds terms with faucet money, submits failing work, then passing work, tries a replay, and gets paid.
   The faucet gives an account once in 7 days. If it says no, `--fund-from KEYFILE` moves 10 test USDC from a key of yours.
4. It makes the buyer's and the supplier's statements, each with the paid line, and checks they have one hash. The
   line's "settled" step is closed from the paying transaction (`knos statement settle-sync`).
5. It checks the archive with the verifier inside it, which needs no Knos, then commits `witness.json`.
6. A failed step says why; `--from STEP` goes on; `--timeout S` gives one command longer (default 600 s). File `witness.json` for the playground's `witness` task (tasks/outside/witness.json).
