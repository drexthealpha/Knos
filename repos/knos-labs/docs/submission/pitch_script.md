# Pitch script (two to three minutes)

Narration only. Every number below is checked by `python scripts/claims_check.py`.

## The problem

Coding agents now open pull requests on their own, and many of them say "tests pass". We measured it: 18.2% of agent
PRs that say tests pass had failing CI at that very commit. A maintainer cannot pay for that claim on trust.

## The product

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

A maintainer funds an issue. An agent claims it with a stake. A reusable workflow runs the repo's checks, and GitHub
signs a token for that run. The Knos escrow on Solana verifies GitHub's signature itself, on chain, and only then pays
the agent. No proof by the deadline, and the maintainer gets the money back plus the stake.

## Why it holds

We attacked our own proof with cheating pull requests: CI green fooled 16/20, Knos fooled 1/20. The fee is 2.5%,
taken only when the agent is paid. The program's upgrade authority is a Squads vault, and we say plainly that its
members are our own keys today, so mainnet stays locked until an outside signer joins.

## Try it

Open drexthealpha.github.io/Knos, paste any agent PR, and see whether its claim is true. Nothing to install.

## The next 12 months (plans, not shipped)

These are plans. Bring in an outside signer and a 24 h time lock on the upgrade multisig. Get an external audit,
then open mainnet. Add more CI issuers beyond GitHub and GitLab.
