# knos-task

A repository for one piece of paid work, made from this template by the "task with no repository" form on the
[Knos](https://github.com/drexthealpha/Knos) site.

What happens here:

To reproduce what Knos says it does, with nothing installed: press **Use this template**, then in your new repository
open **Actions**, choose **knos reproduce** and press **Run workflow**. GitHub signs the report
([how](https://github.com/drexthealpha/Knos/blob/main/docs/reference/REPRODUCE.md)).

For a task:

1. You open an issue that says what you want built, and add the acceptance files the form made
   (`.knos/acceptance/<issue>/`): pairs of an input and the answer it must get.
2. You fund the issue with a comment, `/knos fund <amount> tests`. The money goes into a hold on Solana, and the
   terms are fixed at that moment.
3. Anyone opens a pull request that solves it. Knos runs the solution on every recorded input in a sandbox. When every
   answer matches, GitHub signs that it did, and the hold pays the author. No merge and no decision of yours is
   needed, and nobody can change the terms afterwards.

The files in `.github/workflows/` are copied from
[drexthealpha/Knos/examples](https://github.com/drexthealpha/Knos/tree/main/examples): Knos's two callers, and
`knos-reproduce.yml`, which runs only when you start it by hand. Their comments say what each trigger does and what the
file can and cannot do in this repository. They need no secret.

On Solana devnet today, in test USDC.
