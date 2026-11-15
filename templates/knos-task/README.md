# knos-task

The files of a repository for one piece of paid work. Create an empty public repository of your own and add these
files to it. They are kept in [Knos](https://github.com/drexthealpha/Knos) itself, as `templates/knos-task/`.

What happens here:

To reproduce what Knos says it does, with nothing installed: create an empty public repository of your own, add
`.github/workflows/knos-reproduce.yml` from this folder to it, then open **Actions**, choose **knos reproduce** and press
**Run workflow**. GitHub signs the report ([how](https://github.com/drexthealpha/Knos/blob/main/docs/reference/REPRODUCE.md)).

For a task:

1. You open an issue that says what you want built, and add the acceptance files `knos accept init` makes
   (`.knos/acceptance/<issue>/`): pairs of an input and the answer it must get.
2. You fund the issue with a comment, `/knos fund <amount> checks: none auto`. The test USDC is locked on Solana with the terms, and
   the terms are fixed at that moment.
3. Anyone opens a pull request that solves it. Knos runs the solution on every recorded input in a sandbox. When every
   answer matches, GitHub signs that it did, and the payment program pays the author. No merge and no decision of yours is
   needed, and nobody can change the terms afterwards.

The files in `.github/workflows/` are copied from
[drexthealpha/Knos/examples](https://github.com/drexthealpha/Knos/tree/main/examples): Knos's two callers, and
`knos-reproduce.yml`, which runs only when you start it by hand. Their comments say what each trigger does and what the
file can and cannot do in this repository. They need no secret.

Part of Knos: the Solana side, from the Colosseum entry (v0.3.28), on Solana devnet in test USDC.
