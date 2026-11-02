# Knos on NEAR

Knos carries any research across the valley of death (idea or paper -> demand -> Ready brief -> money held -> paid on verified proof), toward Schmidhuber's vision and Kardashev II/III, connecting 8 billion people to the world's money.

| | |
|---|---|
| **Pays on proof** | A funder sends test USDC with `ft_transfer_call`; the contract holds it against a criteria hash and a deadline. |
| **Proof is a signed CI run** | A GitHub Actions OIDC token, checked in the contract: RS256 in pure Rust, issuer, audience = this contract, repository, workflow, commit and a one-time `jti`. |
| **Refund** | After the deadline, the money goes back to the funder. Fee: 0. |
| **Keys** | GitHub's signing keys are set by 2 of 3 owners. |
| **Network** | NEAR testnet only. Test money. |

## Tests

```bash
cd near/contract && cargo test
bash near/scripts/test-sandbox.sh
```

`cargo test`: 39 unit tests, 13 of them attacks (replayed, forged, re-signed or expired tokens, another repository, workflow or audience, altered criteria, a second payment, an early refund, a release after the refund, a key change by a non-owner, funding in another token).
`test-sandbox.sh` builds both contracts to wasm and runs them on a local near-sandbox node: fund, release, replay, forgery and refund, with the gas each release burns.

## Layout

- `contract/`: the contract (`lib.rs`), RS256 (`rsa.rs`), token parsing (`jwt.rs`), unit tests (`tests.rs`).
- `mock-usdc/`: a NEP-141 test token for the sandbox.
- `sandbox/`: the sandbox test.

Changes since the start of this work: [near-pre...main](https://github.com/drexthealpha/Knos/compare/near-pre...main).
