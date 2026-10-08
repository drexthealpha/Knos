# One transaction, witnessed by you

Test USDC, no monetary value. You need a GitHub account, `gh` logged in, `git`, and `pip install knos`.

1. `python examples/witnessed/witness.py plan --login YOU` lists the 13 steps. It sends nothing.
2. `python examples/witnessed/witness.py run --login YOU` does them in a repository of yours, made from `drexthealpha/knos-task`.
3. It funds terms with faucet money, submits failing work, then passing work, tries a replay, and gets paid.
4. It makes the buyer's and the supplier's statements and checks they have one hash.
5. It checks the archive with the verifier inside it, which needs no Knos, then commits `witness.json`.
6. A failed step says why; `--from STEP` goes on. File `witness.json` for the playground's `witness` task (tasks/outside/witness.json).
