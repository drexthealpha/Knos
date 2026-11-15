# knos

Proves a paper's claim on NEAR testnet from your terminal, with test money. Node 18 or later, no dependencies.

    git clone https://github.com/drexthealpha/Knos && node Knos/npm/knos/knos.mjs

It prints the claim, the sha256 of the test NEAR locked before any agent started, the verdict and the NEAR transactions
of the test money it moved. Give a paper link to prove another claim: `node Knos/npm/knos/knos.mjs https://arxiv.org/abs/1406.2294`.
The package is not on npm yet; once it is published, `npx knos@latest` runs the same file. MIT licensed: https://github.com/drexthealpha/Knos
