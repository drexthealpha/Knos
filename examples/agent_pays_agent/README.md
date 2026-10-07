# Agent pays agent, only when the work is accepted

Two agents with keys of their own, no model call, and an evaluator that is neither. The buyer's money sits in an
escrow that one thing releases: a signed acceptance. `python -m pytest -q tests/test_agent_pays_agent.py` runs both
runs on the simulator with the real program builds.

| who | file | what it does |
|---|---|---|
| buyer | `buyer.mjs` | reads the seller's board, picks a task within its limit, reads the `402`, funds the order, asks again |
| seller | `seller.mjs` | lists its task, sells it under the x402 `knos-order` scheme ([docs/X402.md](../../docs/X402.md)), delivers; `--wrong` delivers bad work |
| evaluator | `evaluator.mjs` | reads the task and the delivery; exit 0 is accepted, exit 1 is not |

Run 1: right work, the evaluator accepts, the escrow pays the seller the amount whole. Run 2: wrong work, no acceptance
is signed, another workflow's signature and an early refund are both refused, and at expiry the buyer has the amount
and the fee back. The signature is GitHub's, over a run of the workflow the order pinned at funding, verified on chain
by `knos-oidc`; `evaluator.mjs` is the `test` check that run reads. In the test a key only a test build trusts signs.

On devnet, with test USDC (the release run; not run yet). Two key files: the payee must be an account other than
the funder, and `buyer.mjs` refuses a board whose payee is its own address.

    cp examples/agent_pays_agent/offer.devnet.json offer.json   # fill repoId, issue, wfSha, seller.githubId
    node examples/agent_pays_agent/seller.mjs --devnet --key seller.json --offer offer.json &
    node examples/agent_pays_agent/buyer.mjs --devnet --key buyer.json --board http://127.0.0.1:4021 --max 5000000
    node examples/x402_attested/live.mjs status --rpc https://api.devnet.solana.com --order ORDER
    node examples/x402_attested/live.mjs refund --rpc https://api.devnet.solana.com --key buyer.json --order ORDER

`buyer.json` needs a little SOL and 5.40 test USDC ([faucet.circle.com](https://faucet.circle.com)). `status` says
`paid` once the seller's pull request is merged with `test` green; in the `--wrong` run it stays `escrowed` and `refund`
returns everything after the offer's 15 minutes. Video shots: [SHOTS.md](SHOTS.md). Node 20 or later, no package to
install. Not built: an evaluator that is itself an agent holding a key the program trusts.
