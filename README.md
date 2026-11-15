# knos-witness

The record of one witnessed transaction of Knos 0.3.23 on Solana devnet, part of Knos's Colosseum entry (tag v0.3.28):
[docs/TRANSACTION.md](https://github.com/drexthealpha/Knos/blob/main/docs/TRANSACTION.md). It is frozen. Its files and
its history are also kept in Knos, under `repos/knos-witness`.

What happened here, in 2026-10:

1. An issue said what to build, with the acceptance files (`.knos/acceptance/<issue>/`): pairs of an input and the
   answer it must get.
2. A comment funded the issue, `/knos fund <amount> tests`. The money was held on Solana until the proof passed, and
   the terms were fixed at that moment.
3. A pull request solved it. Knos ran the solution on every recorded input in a sandbox. When every answer matched,
   GitHub signed that it did, and the payment program paid the author. No merge and no decision of the funder's was
   needed, and nobody could change the terms afterwards.

The files in `.github/workflows/` are the callers of that release, pinned by commit; their comments say what each
trigger did. Reproduce what Knos says, with nothing installed:
[docs/reference/REPRODUCE.md](https://github.com/drexthealpha/Knos/blob/main/docs/reference/REPRODUCE.md).

Solana devnet, test USDC with no monetary value.
