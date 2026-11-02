# Knos on NEAR

Knos carries any research across the valley of death (idea or paper -> demand -> Ready brief -> money held -> paid on verified proof), toward Schmidhuber's vision and Kardashev II/III, connecting 8 billion people to the world's money.

**A company pays a lab or a developer only when GitHub's signed run proves the milestone.** The money waits in a NEAR contract; after the deadline with no proof, the company gets it back. Payout today is in a test token on NEAR testnet; payout on other chains through Chain Signatures is next.
Spending limits cap what an agent may spend. Knos pays only for work that is proven done.

| | |
|---|---|
| **Pays on proof** | A funder sends a test token (NEP-141) with `ft_transfer_call`; the contract holds it against a criteria hash and a deadline. |
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
`test-sandbox.sh` builds both contracts to wasm and runs them on a local near-sandbox node: fund, release, replay, forgery and refund. Measured: the release receipt burns 7.22 Tgas (11.48 Tgas for the whole transaction); the replayed and the forged token are refused; after the deadline the payer gets the money back and a later release is refused.

## On testnet

| | |
|---|---|
| Contract | [`knos-pay-1102.testnet`](https://explorer.testnet.near.org/accounts/knos-pay-1102.testnet), deployed in tx [`2dQUdyp6…`](https://explorer.testnet.near.org/transactions/2dQUdyp6UjrprMKHhamgzdMYyHLt6zY9HZqgRtMk8Xqt) |
| Test token | [`knos-usdc-1102.testnet`](https://explorer.testnet.near.org/accounts/knos-usdc-1102.testnet) (NEP-141, this repo's `mock-usdc`), tx [`D4PoD9do…`](https://explorer.testnet.near.org/transactions/D4PoD9doUA5Lo7wxWRSQEvnpFPcmHXuqitqnXgYoa8sG) |
| Owners | `knos-own1-1102`, `knos-own2-1102`, `knos-own3-1102` (.testnet): any 2 set GitHub's signing keys |
| Wasm | 197,130 bytes, sha256 `55b35f121fa134f8771b702f2d21b965f724bbb8f2a8a04a648c8616254d3aca` |

Read the rules from the chain:

```bash
near contract call-function as-read-only knos-pay-1102.testnet get_rules json-args '{}' network-config testnet now
```

## Layout

- `contract/`: the contract (`lib.rs`), RS256 (`rsa.rs`), token parsing (`jwt.rs`), unit tests (`tests.rs`).
- `mock-usdc/`: a NEP-141 test token for the sandbox.
- `sandbox/`: the sandbox test.

Changes since the start of this work: [near-pre...main](https://github.com/drexthealpha/Knos/compare/near-pre...main).
