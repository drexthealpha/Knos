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
bash near/scripts/verify.sh
```

It prints `150/150 tests passed (101 of them attacks)`: 149 unit tests, then the sandbox flow. Each attack changes one thing and must be refused with the contract's own reason: the token's issuer, audience, expiry, repository, workflow, commit, header, form or signature; the funding message; the key set; a second payment, an early refund or a release after the refund.
`verify.sh` builds both contracts to wasm and runs them on a local near-sandbox node: fund, release, replay, forgery and refund. Measured: the release receipt burns 7.22 Tgas (11.48 Tgas for the whole transaction); the replayed and the forged token are refused; after the deadline the payer gets the money back and a later release is refused.

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

## Attacks on testnet

34 attacks and 3 controls, each a real transaction on the contract above, sent by `scripts/attack_testnet.py`. Tokens are signed with an RSA-2048 test key that two owners set as kid `knos-test`, standing in for GitHub's key, so each row changes one thing.

| Attack | Expected | Actual | Reason | Testnet tx |
|---|---|---|---|---|
| one owner alone sets a key | not applied | done | proposed knos-test: waiting for a second owner | [`DWrU3LJj…`](https://explorer.testnet.near.org/transactions/DWrU3LJjwXJk3nJgrb8uJwjupoLguFxTc6GLUbTPMxr5) |
| the same owner twice | not applied | done | proposed knos-test: waiting for a second owner | [`C4t1cMga…`](https://explorer.testnet.near.org/transactions/C4t1cMgakptAwQGZJeyMYh3oeiaJZDEUuyphWuEem6aQ) |
| a second owner, same key (control) | key set | done | key knos-test set by 2 owners | [`EdmJATYn…`](https://explorer.testnet.near.org/transactions/EdmJATYn42UkYoeEZVYKkmyCSWCuxEvE3KxZFjZrAtbb) |
| a key change by a non-owner | refused | refused | only an owner changes the key set | [`9x2n67Uf…`](https://explorer.testnet.near.org/transactions/9x2n67Ufz4FLmFQvXvxv6gSB2YDctTm8n3q5RtG3ujKH) |
| a 1024-bit key | refused | refused | n must be a 2048-bit RSA modulus | [`FcXQYkzY…`](https://explorer.testnet.near.org/transactions/FcXQYkzY5cjjYTnqB3ooAqRiwFwQwbBCYrYbXFJnzpZH) |
| an honest release (control) | paid | done | a11022034-1: Released | [`C4Cjnaas…`](https://explorer.testnet.near.org/transactions/C4Cjnaasmnss4Y5FevVLPhNFqSarVKsSXALzoBRUKnYV) |
| the same token again (replay) | refused | refused | this token was already used | [`EXQGzgvV…`](https://explorer.testnet.near.org/transactions/EXQGzgvVh4u1YEmowihj7iyLyG16vErmCyBbGDxCVBVo) |
| a second payment of a paid milestone | refused | refused | the milestone is not funded and open | [`4UYgG4QC…`](https://explorer.testnet.near.org/transactions/4UYgG4QCUJga2dJwgKv4xoB9tozHkK8JAwTQ9ozUMokQ) |
| a token from another repository | refused | refused | the token comes from another repository | [`owZYHEd7…`](https://explorer.testnet.near.org/transactions/owZYHEd7ysKgMkL1WrodZcmeeryJL1sk4pLRsT927TG) |
| a token from another workflow | refused | refused | the token comes from another workflow | [`4awcPcNA…`](https://explorer.testnet.near.org/transactions/4awcPcNAGJ7pweR7nWt3vzqAzD4LV36iHJ3ubjedNc6z) |
| a workflow on another branch | refused | refused | the token comes from another workflow | [`HWHijphw…`](https://explorer.testnet.near.org/transactions/HWHijphwEGKhbbY1BZheoe6PDRQn4p8oZNE6GvvcVB47) |
| altered criteria | refused | refused | the criteria are not the ones locked at funding | [`H9TB8vSN…`](https://explorer.testnet.near.org/transactions/H9TB8vSN4QvkNvxPW3uPyNPyc4scfbn52rMit7p31pph) |
| a forged token (unknown key) | refused | refused | the token's key is not in the key set | [`MMc4ja2B…`](https://explorer.testnet.near.org/transactions/MMc4ja2BVCf7Eg9vjpxxaCPYVQ7MAGRzPyPDkBChYwV) |
| a re-signed token (known kid, other key) | refused | refused | the token's signature does not verify | [`DFdeJxq6…`](https://explorer.testnet.near.org/transactions/DFdeJxq6HJaPL1iV9emSotgW4wrUHg12fKiU777RzTp2) |
| claims changed after signing | refused | refused | the token's signature does not verify | [`D8QYNaPC…`](https://explorer.testnet.near.org/transactions/D8QYNaPCp2Le1NbiGaVANYj9L4b313S3oGKGAVDbyJyk) |
| a truncated signature | refused | refused | the token's signature does not verify | [`BSTCiRB2…`](https://explorer.testnet.near.org/transactions/BSTCiRB2GHwGJszsfcbbxaf2JZqgr3Boh2nuCv1Rs9Sq) |
| an expired token | refused | refused | the token has expired | [`12hdJh2N…`](https://explorer.testnet.near.org/transactions/12hdJh2NSB6ynfN7hGhkFoTQNU2ffLtvqs6LT9N3hzKF) |
| another audience | refused | refused | the token's audience is not this contract | [`HC8Ca9rq…`](https://explorer.testnet.near.org/transactions/HC8Ca9rq1MjSidPESXBhWCzFnpTUjMcokLUQefSQbVUi) |
| another issuer | refused | refused | the token is not GitHub's | [`9NvQSWUE…`](https://explorer.testnet.near.org/transactions/9NvQSWUEDX7XnX6M2mWk4CEgUEBTR3fVvkKMZ36cdw2f) |
| alg HS256 | refused | refused | the token is not RS256 | [`E1tsoziq…`](https://explorer.testnet.near.org/transactions/E1tsoziqA5VEC2jRsariUR7dAcyZ1qJZHViRt4aRLxrP) |
| alg none, no signature | refused | refused | the token is not RS256 | [`89vd5KA5…`](https://explorer.testnet.near.org/transactions/89vd5KA55E2xSLLsLwBZiDfoG2mxPWwXdLaJf33LarBo) |
| a token naming no commit | refused | refused | the token names no commit | [`5fbQz1d2…`](https://explorer.testnet.near.org/transactions/5fbQz1d2jEcAqoxUA6His6kGSZeRkxTyvS4T6GFmuGnR) |
| not a JWT | refused | refused | the token is not header.payload.signature | [`A1HWANUh…`](https://explorer.testnet.near.org/transactions/A1HWANUhwAmd714f6q71PK5JKnLYoJfz56GFQoDAWqsF) |
| a milestone that does not exist | refused | refused | no such milestone | [`DVJYQbUD…`](https://explorer.testnet.near.org/transactions/DVJYQbUDqEHbWnUL5rcTxuDyvPTEBtoZwMHLGzRmyhY3) |
| an early refund | refused | refused | the deadline has not passed | [`4U6UB5sh…`](https://explorer.testnet.near.org/transactions/4U6UB5shR5gavJdpfDctXt4PbCeqmAp53wzYKGcf1rij) |
| the private callback called from outside | refused | refused | Method on_paid is private | [`CKcMbaH7…`](https://explorer.testnet.near.org/transactions/CKcMbaH7FC9uKqd2e6TYaytf4Xf6E9N63aBq6pBXbTJt) |
| funding the same id twice | refused | refused | a milestone with this id exists | [`7uBbrcr2…`](https://explorer.testnet.near.org/transactions/7uBbrcr2R6BBhweWhmwkt3rXiM2CGyUmq3pczyQ4r9zn) |
| funding with a past deadline | refused | refused | the deadline is in the past | [`5yCBBfgx…`](https://explorer.testnet.near.org/transactions/5yCBBfgxwM27nbwnJLt2gvFRwmag4qXKdQ7sm89cfi9M) |
| funding without a criteria hash | refused | refused | criteria_hash must be 64 hex | [`83LUzgpt…`](https://explorer.testnet.near.org/transactions/83LUzgptep54kpTXBSYtnYzy2MnpwgeK5i3fqExqGsEo) |
| funding for an unknown chain | refused | refused | payee_chain | [`Dai6nwr9…`](https://explorer.testnet.near.org/transactions/Dai6nwr97WMhWkzWLCu56ypE41jwLtnMm2tNnKv7a8VK) |
| a workflow outside the repository | refused | refused | repository and workflow | [`2Jw9tjV1…`](https://explorer.testnet.near.org/transactions/2Jw9tjV1JE5Nr2pnizFLmLSfP4kJjJtk1jCKzEzzBay4) |
| funding in another token | refused | refused | only the configured USDC funds a milestone | [`3SBkVMqE…`](https://explorer.testnet.near.org/transactions/3SBkVMqEHYNgX4YBDZkiVgULtVPs56VvMzXQXkKGw9iY) |
| a token under a removed key | refused | refused | the token's key is not in the key set | [`J4fUbDmv…`](https://explorer.testnet.near.org/transactions/J4fUbDmvjShLjGEwWCp9V1UhWpo4jppnDXqjSZr5Tude) |
| a release after the deadline | refused | refused | the deadline has passed: only a refund is possible | [`6RtvrxM5…`](https://explorer.testnet.near.org/transactions/6RtvrxM5TzvjJoqUkjmYjuWqbEDBaNCLDrQNime1SfMc) |
| a refund after the deadline, sent by anyone (control) | refunded | done | a11022034-9: Refunded | [`JBUVS3NH…`](https://explorer.testnet.near.org/transactions/JBUVS3NH2UjHWS5gSxipFgosMrQHGVcV61URnLapeyCa) |
| a release after the refund | refused | refused | the milestone is not funded and open | [`HPxnhyTV…`](https://explorer.testnet.near.org/transactions/HPxnhyTV9VSGvRLNzcf8ZC2BS5ya1CCtUGe9CFPSDg6p) |
| a second refund | refused | refused | the milestone is not funded and open | [`7BmBwJLN…`](https://explorer.testnet.near.org/transactions/7BmBwJLNACJSgXu8cSJU8HHgkjLwaLxZGwU64TGHreJn) |

## Layout

- `contract/`: the contract (`lib.rs`), RS256 (`rsa.rs`), token parsing (`jwt.rs`), unit tests (`tests.rs`).
- `mock-usdc/`: a NEP-141 test token for the sandbox.
- `sandbox/`: the sandbox test.

Changes since the start of this work: [near-pre...main](https://github.com/drexthealpha/Knos/compare/near-pre...main).
