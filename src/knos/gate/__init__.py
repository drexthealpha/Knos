"""Knos Gate: a maintainer's check on every outside pull request, against tests its author could not see.

    .knos/gate.yml            the maintainer's config (knos.gate.config: schema, loader, defaults)
    sealed hidden tests       a bundle the pull request's author cannot read (a repository secret or a private
                              repository), sealed by its sha256 in .knos/gate.yml, run on the pull request's code in
                              a sandbox with no network and no token; only counts leave it (knos.gate.sealed)
    cheat library             test edits, files outside scope, data tampering, workflow edits: REFEREE's
                              `knos.cheats` when installed, else the small local rule set (knos.gate.cheatlib)
    one check, one comment    exactly one status check ("Knos Gate") and one comment per pull request, each
                              updated in place (knos.gate.report, knos.gate.github)
    receipt                   a signed, offline-verifiable receipt of the run (knos.receipt2)
    bounties                  optional: a funded issue is paid to the first pull request that passes the hidden
                              tests and is merged; failing claims are closed (knos.gate.bounty)

Two ways to run it: the GitHub Action (actions/gate: a `workflow_run` job named "Knos Gate", after the
`pull_request` run of knos-gate-pr.yml) or the GitHub
App (github-app/, which owns the check run and the comment and dispatches the same workflow). docs/reference/REFEREE.md is the page.
Nothing here needs a wallet, a token on chain or an escrow unless bounties mode is on.

Not the same thing as knos.verdict_gate (the hand-off between two jobs of prove.yml), knos.settle.v2.gate (the
upgrade gate's on-chain record) or `knos proof gate` (the free claims check of action.yml)."""

CHECK_NAME = "Knos Gate"
MARKER = "<!-- knos-gate:v1 -->"
