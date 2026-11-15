# knos-playground

Frozen. This was the playground of Knos's Colosseum entry (tag v0.3.28). The playground is now Knos's own issues:
[docs/reference/PLAYGROUND.md](https://github.com/drexthealpha/Knos/blob/main/docs/reference/PLAYGROUND.md). This
repository is kept, read as it was, because the Colosseum judge path uses its pull request 35. Its files and history are
also in Knos, under `repos/knos-playground`. The faucet that funded new issues is turned off.

How it worked, with a GitHub account and nothing else:

**Fund a test task.** An issue held the line `/knos fund 5 checks: none auto`: 5 test USDC from the devnet faucet were
held on Solana for that issue until the proof passed, and Knos answered in a comment.

**Take one.** Edit `words.py` so that it prints the words of a line in reverse order, and open the pull request with
`Closes #<the issue's number>`. The checks in `.knos/acceptance/<number>/` ran the file as a separate process and
compared what it printed. When every answer matched, GitHub signed that it did and the payment program paid the
author: to the wallet they bound, or held for their account until they bound one. Nobody merged and nobody decided.

**Take a funded task.** Issues labelled `knos-funded` were small programming tasks, each with its own file under
`tasks/`. A maintainer merged a pull request that passed the check, and the merge paid the author's account.

It is test money: the faucet minted it, nobody can withdraw it from the faucet's balance, and it is worth nothing.
What was counted, and how: [docs/reference/PLAYGROUND.md](https://github.com/drexthealpha/Knos/blob/main/docs/reference/PLAYGROUND.md).

Solana devnet, test USDC.
