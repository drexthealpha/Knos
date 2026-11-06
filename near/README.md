# Knos on NEAR

Knos pays agents only when the test passes.

## For a reader checking this project

**Problem.** When you pay an AI agent for work, you pay for its claim that the work is done. Nobody checks the claim
before the money moves.

**What it does.** A job's bid waits in a NEAR contract against a test locked by its hash. Agents take the job and submit.
A checker runs the locked test on each output and signs a token for the one that passes; the contract checks that token,
then pays. The agent whose output fails is paid 0.

Do this, see that:
- Open https://drexthealpha.github.io/Knos/near/ and click Post a job - see "Paid: Agent A 1000, Agent B 0 test units"
  within seconds, with a link to the payment on NEAR testnet (4.0, 7.0 and 4.5 s on three walks, 6 Nov 2026).
- Click a take, submit or paid link under The job - see each step as its own testnet transaction.
- Run `python near/scripts/try_testnet.py <you>.testnet` - see your own copy of both contracts release on a signed token
  and refund after the deadline ([Try it on testnet](#try-it-on-testnet)).
- Run `bash near/scripts/verify.sh` - see the contract's sandbox tests and attacks pass ([Tests](#tests)).

**What was built in the window.** Everything under `near/` and the hosted runner `apps/wanted/knos_wanted/near_live.py`:
the diff from the tag `pre-hackathon` (31 Oct 2026) is
https://github.com/drexthealpha/Knos/compare/pre-hackathon...main (`near/` did not exist at that tag). The tag
`hackathon-submission` is added when the code is final.

**Built before, on another chain (Q-002).** Knos existed before this window on Solana devnet: the programs in
`programs-v2/` and the Python package `knos` in `src/knos/` that drives them. Only the NEAR work above is the entry.
The NEAR contract can pay a milestone out on Solana devnet through NEAR Chain Signatures
([Paid on Solana by Chain Signatures](#paid-on-solana-by-chain-signatures)).

**Own older code and libraries (Q-005).** The hosted runner reuses the older app server in `apps/wanted/` (routes, rate
limits) and its Render deploy. The libraries are listed under [Disclosure](#disclosure). Most of the code was written with Claude Code.

**Tracks it fits.** Agent Economy (`agents`): agents with their own sub-accounts whose keys can only call the jobs
contract, under a spend cap. AI Swarms (`swarms`): two agents on one job, paid by the result of a locked test.

**The test is locked before money is held and checked before money moves: nobody is paid on a claim.** (Demand is checked first, by Qloo, on the [site](https://drexthealpha.github.io/Knos/).)

**A company pays a lab or a developer only when GitHub's signed run proves the milestone.** The money waits in a NEAR contract; after the deadline with no proof, the company gets it back. The payout is paid on NEAR, or on Solana through NEAR Chain Signatures: the contract checks the transfer and has the MPC network sign it.
Spending limits cap what an agent may spend. Knos pays only for work that is proven done.

| | |
|---|---|
| **Pays on proof** | A funder sends a test token (NEP-141) with `ft_transfer_call`; the contract holds it against a criteria hash and a deadline. |
| **Proof is a signed CI run** | A GitHub Actions OIDC token, checked in the contract: RS256 in pure Rust, issuer, audience = this contract, repository, workflow, commit and a one-time `jti`. Paid on a real one: [run 41651312325](https://github.com/drexthealpha/Knos/actions/runs/41651312325), release [`82N9tRK8…`](https://explorer.testnet.near.org/transactions/82N9tRK8BvB4FpA9yUJb6L6q5FTwT3J1MCzQzN2fWWqj). |
| **Refund** | After the deadline, the money goes back to the funder. Fee: 0. |
| **Keys** | GitHub's signing keys are set by 2 of 3 owners (`scripts/github_keys.py`). |
| **Network** | NEAR testnet only. Test money. |

## Run one now

Open [drexthealpha.github.io/Knos/near/](https://drexthealpha.github.io/Knos/near/) and click **Post a job**. You see
"Paid: Agent A 1000, Agent B 0 test units, live" and a link to the payment on NEAR testnet, within seconds: a job is
kept ready, posted against its locked test and tried by both agents, so your click sends the payment to the one whose
output passed. It runs on Knos's own capped test account (`live.knos-swarm-1105.testnet`, test tokens only): 20 runs
a day, three every 10 minutes from one address; past a cap the page shows the last run and says "Replay". The same job from a
terminal: `pip install knos`, then `knos near-job`.

## Work in the window

Every change since the work began: [pre-hackathon...main](https://github.com/drexthealpha/Knos/compare/pre-hackathon...main)
(the tag `pre-hackathon` is the commit before the first line of `near/`).

No Rust is needed to check or deploy the contract: `near/wasm/` holds the built files and `near/wasm/SHA256SUMS` their
hashes. `cd near/wasm && sha256sum -c SHA256SUMS` prints `knos_near.wasm: OK` and `knos_mock_usdc.wasm: OK`
(`a5fc5861…`, 280,651 bytes, is the jobs contract deployed at `jobs.knos-swarm-1105.testnet`). Building them again and
every test: `bash near/scripts/verify.sh` (Rust with `wasm32-unknown-unknown` and `cargo-near` 0.22.0).

## Try it on testnet

Your own copy of the contract, then a release and a refund. About 4 minutes after step 2. You need Python 3.10+ with `cryptography`, and [near-cli-rs](https://github.com/near/near-cli-rs/releases) 0.30.1.

1. Make a testnet account: `near account create-account sponsor-by-faucet-service <you>.testnet autogenerate-new-keypair save-to-legacy-keychain network-config testnet create`. You see "New account <you.testnet> created successfully." and its transaction.
2. Run `python near/scripts/try_testnet.py <you>.testnet`. You see six sub-accounts made and the two contracts deployed from `near/wasm/` (sha256 in `near/wasm/SHA256SUMS`).
3. The script sets a test signing key by 2 of 3 owners, funds `m1` and releases it on a signed token. You see "release m1 on a signed token: done" with its transaction.
4. It sends the same token again. You see it refused.
5. It funds `m2` with a 1-minute deadline, waits, and refunds it. You see "m1: Released" and "m2: Refunded".

The page in `web/` runs the same flow from a browser (`python near/web/serve.py`, checked by `web/test-flow.mjs`), but on the maintainer's test accounts (`knos-*-1102.testnet`, `knos-pay2-1102`), whose keys only that machine holds; it does not use your account yet. `web/story/` takes a milestone apart as you scroll.

## A job two agents try

Post a job with a locked test and a bid; two agents take it; the checker runs the locked test on each output, and only
the agent whose output passes is paid. You need Python 3.10+ with `cryptography` and near-cli-rs 0.30.1; it runs on the
maintainer's test accounts, whose keys only that machine holds (as the page in `web/` does).

1. Run `NEAR_CLI=<near> python near/web/serve.py` and open `http://127.0.0.1:8790/`. You see "Paid only when the test passes" and a **Post a job** button.
2. Click **Post a job**. You see "Paid: Agent A 1000, Agent B 0 test units." and the job's six transactions.
3. Click **Try both** under Guardrails. You see two lines starting "refused", each with its transaction: a payment over agent B's cap, and a release with no passing proof.
4. Open `http://127.0.0.1:8790/embed.html` from another page or origin and click **Pay with any wallet**. You see a NEAR Intents 1Click quote for paying 1 USDC from Base (dry: nothing is spent), then a second click pays the bid on testnet.

The rules are in [`agents/RULES.md`](agents/RULES.md): the job's test is locked by its sha256 at funding, each agent is a
sub-account of `knos-swarm-1105.testnet` that signs with a function-call key allowed only `take`, `submit` and `spend` on
the jobs contract (its full-access key deleted), and the checker's key is set by 2 of the 3 owners. `web/test-job.mjs`
walks these four steps in a fresh browser. One run, 5 Nov 2026:

| Step | Transaction |
|---|---|
| Job posted: 1000 test units against the locked test `0b0f037d…` | [`7VS43unm…`](https://explorer.testnet.near.org/transactions/7VS43unmH6GMv36GNBivvcNB8Bxv2CRKFvHKiLcbu7qu) |
| Agent A takes it, submits its output | [`GzghavUR…`](https://explorer.testnet.near.org/transactions/GzghavURW39UivrETnWFxeunAwEv5Cpm5tKUmhejBQyT), [`oXq8gV4u…`](https://explorer.testnet.near.org/transactions/oXq8gV4u6desS1GuJdK1ZCiTKo4QNAumEQTnTC69A8v) |
| Agent B takes it, submits its output | [`FmSfyLQ4…`](https://explorer.testnet.near.org/transactions/FmSfyLQ4tu2kc4C9rWgjEP1kAo5788EufnVUWeLsJfNt), [`9CYdyki2…`](https://explorer.testnet.near.org/transactions/9CYdyki2gTVnfr31Ufjirs6j99jdjYU8Zk4yseKsef9z) |
| The checker: A 5 of 5 cases pass; B fails; the bid paid to A, 25.4 s after the check began | [`5caS1jXH…`](https://explorer.testnet.near.org/transactions/5caS1jXHAj7FbUZRMQog7nqgaBk4baDBkvBEYAQjbnpH) |
| Agent B pays 2 on a cap of 1: "over the spend cap: 0 spent, 2 asked, cap 1" | [`FdJPJf7R…`](https://explorer.testnet.near.org/transactions/FdJPJf7RLdErvMBdeUkeUWdhqw4VGNEKtw5aVD4VnK4y) |
| Agent B takes an open job's bid with a token it signed itself: "the token's signature does not verify" | [`E5GUcVks…`](https://explorer.testnet.near.org/transactions/E5GUcVks55r9Rn4b1HJBJagDB1bFbL8YMj41UFHFeHan) |
| The embedded button pays a bid on testnet after its 1Click quote | [`32suEFMY…`](https://explorer.testnet.near.org/transactions/32suEFMYv7JEzfGLH9vNdpHs81BmVfHzbW7oMPMShxKX) |

Agent A was paid 1000; agent B was paid 0. NEAR Intents has no testnet, so the 1Click call is a dry quote only, with 0
spent on mainnet. The checker runs an agent's output in a subprocess with a 20 s limit and no environment; it is a
test-money demo, not a sandbox for hostile code.

## Tests

Every push that changes `near/` runs them on GitHub: [the `near-tests` runs](https://github.com/drexthealpha/Knos/actions/workflows/near-tests.yml).
Open the newest run, then its `verify` job: the step `near/scripts/verify.sh` ends with the line below. With Rust
(the `wasm32-unknown-unknown` target and `cargo-near` 0.22.0) the same on your machine:

```bash
bash near/scripts/verify.sh
```

It prints `208/208 tests passed (146 of them attacks)`, the contract's unit tests and then the sandbox flow, and fails when that print is not this line. Each attack changes one thing and must be refused with the contract's own reason: the token's issuer, audience, expiry, repository, workflow, commit, header, form or signature; the funding message; the key set; a second payment, an early refund or a release after the refund; for a job, a token for another output, job, test or payee, a checker key against a GitHub token and back, an agent that never took the job, a spend over the cap.
`verify.sh` builds both contracts to wasm and runs them on a local near-sandbox node: fund, release, replay, forgery and refund. Measured: the release receipt burns 7.33 Tgas (11.68 Tgas for the whole transaction) in the latest verify.sh run (5 Nov 2026, a fresh clone); the replayed and the forged token are refused; after the deadline the payer gets the money back and a later release is refused.

## On testnet

| | |
|---|---|
| Contract | [`knos-pay-1103.testnet`](https://explorer.testnet.near.org/accounts/knos-pay-1103.testnet), first deployed in tx [`6Uoen72K…`](https://explorer.testnet.near.org/transactions/6Uoen72KUZnDy1PCknZx5iEQNzfWY2hGgyGmgTdpjAfp); this build since 3 Nov 2026, tx [`AcFJP4Ch…`](https://explorer.testnet.near.org/transactions/AcFJP4ChbxF4Vuwx6qAdHNuugbHgcVNuVcprnzpx1Mfk), code hash `4ZwgX56fbcChxPwP6nu5oJJ8vWYtB2Az9y4jF2K6KcfR` |
| Test token | [`knos-usdc-1102.testnet`](https://explorer.testnet.near.org/accounts/knos-usdc-1102.testnet) (NEP-141, this repo's `mock-usdc`), tx [`D4PoD9do…`](https://explorer.testnet.near.org/transactions/D4PoD9doUA5Lo7wxWRSQEvnpFPcmHXuqitqnXgYoa8sG) |
| Owners | `knos-own1-1102`, `knos-own2-1102`, `knos-own3-1102` (.testnet): any 2 set GitHub's signing keys |
| Wasm | `wasm/knos_near.wasm`, 280,651 bytes, sha256 `a5fc586102b9c1b8e68011c8e263563f2b87de113413ff04d5dcfb84321ac50e`, code hash `CAwSqmYHJ7FnW88ivkm9zxczyKstJrGSkmU1pXzyMQ3X`: the jobs contract [`jobs.knos-swarm-1105.testnet`](https://explorer.testnet.near.org/accounts/jobs.knos-swarm-1105.testnet), deployed in [`GGLvdmu5…`](https://explorer.testnet.near.org/transactions/GGLvdmu5ZQvKQVZYT19AYPJRL91GkkozDVkHCNZPPXWt). `knos-pay-1103` runs the build before the jobs: 223,557 bytes, sha256 `3503799e…` (the code hash above) |

Read the rules from the chain:

```bash
near contract call-function as-read-only knos-pay-1103.testnet get_rules json-args '{}' network-config testnet now
```

## Paid on Solana by Chain Signatures

`sign_payout` takes the unsigned Solana message for a released milestone. The contract accepts only one SPL `TransferChecked` of exactly the milestone's amount, in the mint and to the token account locked at funding, then asks `v1.signer-prod.testnet` (path `knos-solana-1`, Ed25519) to sign it. A relayer adds the signature and broadcasts; no Solana key is held anywhere.

The payout moves tokens held since funding. At funding the funder moves the amount from its own Solana token account into one owned by the contract's derived address; the payout is the transfer of exactly those tokens, and nothing is minted on the way. A milestone released for a Solana payee with no payout signature by its deadline is refunded like an unreleased one, so it never stays locked; once its payout is signed, it is not.

`scripts/solana_payout.py run` does both on [`knos-pay-1103.testnet`](https://explorer.testnet.near.org/accounts/knos-pay-1103.testnet) (code sha256 `3503799e…`), derived Solana address `DUxGyghGoZNZu85zVJXHLAgsrA3rBt3eVDSGmhk8bzBi`, on 3 Nov 2026:

| Step | Transaction |
|---|---|
| The funder's 1,000,000 test units moved into the derived address's account, held there | [`5zf4swfJ…`](https://explorer.solana.com/tx/5zf4swfJNBMv7JBvMpvQC7nHxL6SU93GRLZ1Vj7DRv8GqZWztYwywnPqxFUT3sYKHRCjZ8aJgy1stLvWa9Wdj8oo?cluster=devnet) |
| Milestone funded for the Solana payee | [`EWepDj2u…`](https://explorer.testnet.near.org/transactions/EWepDj2uQ3gESJrrgyKMmbZgjj9iHr9raCwa8RSSpMAD) |
| Released on a token | [`EVaDjqNV…`](https://explorer.testnet.near.org/transactions/EVaDjqNVUBqVypESpGCFwsbDv2eFBJxd8JZjNmP25wTb) |
| Transfer of the held units checked, signed by the MPC network | [`4eJPkBn5…`](https://explorer.testnet.near.org/transactions/4eJPkBn5jiAoGGBayYKVmreHcL5nqFCLhnRD1Rw4kKUR) |
| The 1,000,000 held units paid on Solana devnet (held account: 1,000,000 before, 0 after) | [`e4e19KWt…`](https://explorer.solana.com/tx/e4e19KWtALEZ5mBHiBjpH5YKuzyHf4bVJyCqDYfcE1UY3smbhkbADxEogho2Sy9DhhqPdWyJCxgTEjMSrjrtMrJ?cluster=devnet) |
| A second milestone released, never signed: refund before the deadline refused | [`Ce2p5iEP…`](https://explorer.testnet.near.org/transactions/Ce2p5iEPxLCAVRKLxTNC37uMb1kLFamLMquFWKhPSsoZ) |
| The same milestone refunded after its deadline: the payer's 1,000,000 test units back | [`A67yep8D…`](https://explorer.testnet.near.org/transactions/A67yep8D8g55KxLjySFUqsDLn7J9AdLFEqvidpaHFmVB) |

Not built: when a released Solana milestone is refunded on NEAR, the tokens already held by the derived address stay there; a signed transfer back to the funder is not written yet.

## The payee needs no NEAR for gas

`relayer/relay.py` is a NEP-366 relayer that pays only for calls to one Knos contract (`knos-pay2-1102.testnet` in the test). `scripts/test_gasless.py` has the payee sign a release as a delegate action; the relayer sends it ([`4XpFZwBM…`](https://explorer.testnet.near.org/transactions/4XpFZwBMGtkPWzCdkwLZkDtB95EPiAWUz7orAPRsyAJG)) and the payee's NEAR balance is the same to the yoctoNEAR. Every other call the test sends is refused, the token contract's `ft_transfer` among them, and the test prints each with the relayer's reason (the relayer also writes them to its local `relay.log`, not kept in the repository).

## An agent that checks who it pays

`agent/guard.py` answers allow, warn or block for a receiver, from chain: no such account or on the shared blocklist (`agent/blocklist.json`, each entry with its evidence) is a block; a contract, an account under 7 days old or code changed in the last day is a warning that a person resolves. `scripts/test_agent_guard.py` gives the agent a key that can call only `release`, `refund` and `sign_payout` here, then a task with an injected instruction to pay two other accounts: both are refused, and the chain refuses the key on the token contract.

## A locked eval

`eval/attempts.json` holds 60 attempts, 30 honest and 30 cheating, each with a green CI run; its sha256 (`eval/attempts.sha256`) was committed before the first run. `cargo test locked_eval -- --nocapture` sends each through the contract, prints the counts with 95% Wilson intervals, and asserts them: every cheating attempt refused, every honest one paid, and plain CI pass/fail paying every cheat.

Read it for what it is. Each cheat is one of the four things the contract checks (a run from another branch or a pull request, another repository, a replayed token, altered criteria), and each carries a green CI run by construction, so the result shows that those checks run on every attempt. It does not measure cheats the contract does not look for: tests edited and merged to main are outside what it can see.

## Attacks on testnet

36 attacks and 4 controls, each a real transaction on the contract above. The first 37 rows were sent by `scripts/attack_testnet.py`, with tokens signed by an RSA-2048 test key that two owners set as kid `knos-test`, standing in for GitHub's key, so each row changes one thing. The last 3 were sent by `.github/workflows/near-release.yml` ([run 41651312325](https://github.com/drexthealpha/Knos/actions/runs/41651312325)) with that run's own GitHub token, kid `38826b17-6a30-5f9b-b169-8beb8202f723`.

| Attack | Expected | Actual | Reason | Testnet tx |
|---|---|---|---|---|
| one owner alone sets a key | not applied | done | proposed knos-test: waiting for a second owner | [`13QkRje9…`](https://explorer.testnet.near.org/transactions/13QkRje9gXLXmVcquyaMTpvCT6C1p6XLbJ3AC3iUyUt5) |
| the same owner twice | not applied | done | proposed knos-test: waiting for a second owner | [`5Hq9vePk…`](https://explorer.testnet.near.org/transactions/5Hq9vePkiaqrwVL7n6GH8Lcusk9TT654SJkrPryp8afz) |
| a second owner, same key (control) | key set | done | key knos-test set by 2 owners | [`8buBe2cH…`](https://explorer.testnet.near.org/transactions/8buBe2cHnNnN6VKm1QBdVUmLh6sQw3AzQc8CxzsovkkV) |
| a key change by a non-owner | refused | refused | only an owner changes the key set | [`FZWCRz4N…`](https://explorer.testnet.near.org/transactions/FZWCRz4NxD9RfAkr4jwmUWx15v2VTmuXZG6TxLQhp6Sm) |
| a 1024-bit key | refused | refused | n must be a 2048-bit RSA modulus | [`C4dSb9TZ…`](https://explorer.testnet.near.org/transactions/C4dSb9TZh526xBkRSdkAdsHJXMzegTgKTsBRdXDKyWDn) |
| an honest release (control) | paid | done | a11030449-1: Released | [`J9wcy43C…`](https://explorer.testnet.near.org/transactions/J9wcy43Cmrm2hFtTzar9AtVuZVvG7AN8SB7FFptnahjn) |
| the same token again (replay) | refused | refused | this token was already used | [`5N969ghk…`](https://explorer.testnet.near.org/transactions/5N969ghkXCb7FuLZH2cfGF12V2M3sXNF7wpjc2p54pe) |
| a second payment of a paid milestone | refused | refused | the milestone is not funded and open | [`NyiJNrBJ…`](https://explorer.testnet.near.org/transactions/NyiJNrBJ5M6gQyFoNKUG5X69mZaa8hVzLgWdiv4kfPk) |
| a token from another repository | refused | refused | the token comes from another repository | [`DdPbefRQ…`](https://explorer.testnet.near.org/transactions/DdPbefRQCu7BUkktvp4k8dmf2Cm5QPTxcn2jHqSpqGvh) |
| a token from another workflow | refused | refused | the token comes from another workflow | [`88r79JUm…`](https://explorer.testnet.near.org/transactions/88r79JUmEFA5dFkNwWCqhTqtAbgZJcFxH2LnLmX7HmvE) |
| a workflow on another branch | refused | refused | the token comes from another workflow | [`GLcpLbnx…`](https://explorer.testnet.near.org/transactions/GLcpLbnxWHaPeVaQpbxKG32BduVW5FaRtVAJzJFggj67) |
| altered criteria | refused | refused | the criteria are not the ones locked at funding | [`35b6Bq2H…`](https://explorer.testnet.near.org/transactions/35b6Bq2HeyX9MZntAHZqndzPfy7ZpjhSoC3KErU9Jr7u) |
| a forged token (unknown key) | refused | refused | the token's key is not in the key set | [`DiSbnkxN…`](https://explorer.testnet.near.org/transactions/DiSbnkxNEFG8nCqcjChGmunEy7ccH5Jvs1upQugL8yLN) |
| a re-signed token (known kid, other key) | refused | refused | the token's signature does not verify | [`CNuKxmNH…`](https://explorer.testnet.near.org/transactions/CNuKxmNHrHHvgBGJXpJWxKAS2BvTY3gk3Vwv4dcEDZDc) |
| claims changed after signing | refused | refused | the token's signature does not verify | [`7ts4yPyb…`](https://explorer.testnet.near.org/transactions/7ts4yPybtMHBeJSXD2BsuUhXnjKHESroG3T8VmwpDonA) |
| a truncated signature | refused | refused | the token's signature does not verify | [`DRHNBrGL…`](https://explorer.testnet.near.org/transactions/DRHNBrGLVwk964VePrupUEvKFrA6vGTVnBkhdcja5uDg) |
| an expired token | refused | refused | the token has expired | [`C5pBDNVL…`](https://explorer.testnet.near.org/transactions/C5pBDNVL7wMDPQm39jdqBSgiNDmupUcNCFLUnjgBiKWu) |
| another audience | refused | refused | the token's audience is not this contract | [`95MRk185…`](https://explorer.testnet.near.org/transactions/95MRk185B74knL43BqeqKK7LPyKms3qdf6SqNeHUL6k9) |
| another issuer | refused | refused | the token is not GitHub's | [`8VQA6SVP…`](https://explorer.testnet.near.org/transactions/8VQA6SVPkwU3bTzmzw1znVXeXBiRpEy7kkFr7P1o2jmm) |
| alg HS256 | refused | refused | the token is not RS256 | [`bb6ZiMAS…`](https://explorer.testnet.near.org/transactions/bb6ZiMASMGwNtWvfA1LEwj4XW8mdfBgVke9hTezHwmJ) |
| alg none, no signature | refused | refused | the token is not RS256 | [`oi7eSCkt…`](https://explorer.testnet.near.org/transactions/oi7eSCktX4rwNffGKUQjvjonctNfPi6xPuhkp2B1kDx) |
| a token naming no commit | refused | refused | the token names no commit | [`36pEPxJe…`](https://explorer.testnet.near.org/transactions/36pEPxJeuj3mHcWQffm51YwGbMJvjXRY5ERmtn3AR529) |
| not a JWT | refused | refused | the token is not header.payload.signature | [`CfpTUhNN…`](https://explorer.testnet.near.org/transactions/CfpTUhNN5cin5rnzQFpfmZkN2VfjV3fSWfQyECaZvx3m) |
| a milestone that does not exist | refused | refused | no such milestone | [`3qJyZWBi…`](https://explorer.testnet.near.org/transactions/3qJyZWBi2okDjdH78ULmuqUKAwwA9TNHnRiE9dvai7Fx) |
| an early refund | refused | refused | the deadline has not passed | [`CdrfBixS…`](https://explorer.testnet.near.org/transactions/CdrfBixSdTQx5C7GbtYuenG7RS3fjCwi7iKjF5Vt13JF) |
| the private callback called from outside | refused | refused | Method on_paid is private | [`7L5b2MNi…`](https://explorer.testnet.near.org/transactions/7L5b2MNik5tmKUuNv2cTvzkjYbq8uPXGYtAD8LG2A5FP) |
| funding the same id twice | refused | refused | a milestone with this id exists | [`FbZib4EA…`](https://explorer.testnet.near.org/transactions/FbZib4EA1tyibRnRwAjdM6Qfw3X8weDuKPFX3L4U27Fs) |
| funding with a past deadline | refused | refused | the deadline is in the past | [`DNm46bgg…`](https://explorer.testnet.near.org/transactions/DNm46bggsBRbTTsekByBXbZNpghesGrmqJ93kwAyFzeQ) |
| funding without a criteria hash | refused | refused | criteria_hash must be 64 hex | [`DVwYdi1S…`](https://explorer.testnet.near.org/transactions/DVwYdi1SUjWrFYytpWZincAmkLJNQuzZ4sqb6ZkpaR4x) |
| funding for an unknown chain | refused | refused | payee_chain | [`3ENxYzgY…`](https://explorer.testnet.near.org/transactions/3ENxYzgY9Df4YWkivvuEvmLhytEit9PjBLowSyXMxp4j) |
| a workflow outside the repository | refused | refused | repository and workflow | [`51m36aiT…`](https://explorer.testnet.near.org/transactions/51m36aiTxVytwLRuRkG7yhtNrJz7BGxqFT4yGbS9eECW) |
| funding in another token | refused | refused | only the configured USDC funds a milestone | [`9RNJwFWj…`](https://explorer.testnet.near.org/transactions/9RNJwFWjBytYYyDqcFFrMsXFWvRs6t1SLPiWAUpJibPw) |
| a token under a removed key | refused | refused | the token's key is not in the key set | [`14NEB4zZ…`](https://explorer.testnet.near.org/transactions/14NEB4zZZ753EMj8jLcaBdQiWKHjugDPigSDxUNzq3Qm) |
| a release after the deadline | refused | refused | the deadline has passed: only a refund is possible | [`AjXQma9b…`](https://explorer.testnet.near.org/transactions/AjXQma9bfPMKcx58cuqK5ReYZpa8HD9RsWyt8EYCsQ4r) |
| a refund after the deadline, sent by anyone (control) | refunded | done | a11030449-9: Refunded | [`EYVQLExx…`](https://explorer.testnet.near.org/transactions/EYVQLExxFvyXTXkk5iri7vaZNt7g82hExRvM8GKRqN5G) |
| a release after the refund | refused | refused | the milestone is not funded and open | [`HRE3ykMo…`](https://explorer.testnet.near.org/transactions/HRE3ykMo1rK6vTY1LxGWjRY87D47eWPqUd8vZDjDndfi) |
| a second refund | refused | refused | the milestone is not funded and open | [`AvcimeGt…`](https://explorer.testnet.near.org/transactions/AvcimeGtYKotYE6nFUtLXqhb3NAXvBUjtTAV68DrA1ai) |
| a real GitHub token from this workflow (control) | paid | done | n1-milestone-11031410: Released, 1,000,000 test units to the payee, 12.13 Tgas | [`82N9tRK8…`](https://explorer.testnet.near.org/transactions/82N9tRK8BvB4FpA9yUJb6L6q5FTwT3J1MCzQzN2fWWqj) |
| the same real token on a second milestone of this workflow | refused | refused | this token was already used | [`HcZ8nBuQ…`](https://explorer.testnet.near.org/transactions/HcZ8nBuQYuYU5LKRVceSfXVdqBnLrj1shyddj3EQBsM2) |
| the same real token on a milestone funded for another workflow | refused | refused | the token comes from another workflow | [`2H16uPeH…`](https://explorer.testnet.near.org/transactions/2H16uPeHibucBssbaEexq9TPyxqWx9hTjHKMRRfmJbfe) |

## Layout

- `contract/`: the contract (`lib.rs`), RS256 (`rsa.rs`), token parsing (`jwt.rs`), the Solana payout check (`solana.rs`), unit tests (`tests.rs`, `tests/`).
- `mock-usdc/`: a NEP-141 test token for the sandbox.
- `sandbox/`: the sandbox test.
- `relayer/`: the gas relayer. `agent/`: the receiver guard. `agents/`: the two agents, the checker, the job's locked test and its rules.
- `web/`: the page and its server (`serve.py`, `jobs_api.py`), the pay button (`pay.js`); `web/story/`: the scroll story. `wasm/`: the built contracts.

Changes since the start of this work: [near-pre...main](https://github.com/drexthealpha/Knos/compare/near-pre...main).

## Disclosure

Who wrote it: Claude Code (Anthropic's coding agent) wrote most of the code in this folder. The founder set each task and reviewed each change before it was merged. Commits carry the founder's account.

No starter template: the first commit of this folder (6413e89) adds each crate as written, with no generated scaffold in the history. The test token in `mock-usdc/` uses the `FungibleToken` implementation from `near-contract-standards`, as its own documentation shows. The contract's checks are this repository's own code (`contract/src/rsa.rs`, `jwt.rs`, `solana.rs`), with no crypto crate among the contract's dependencies (hashing uses the NEAR runtime's own sha256).

Libraries, at the versions in each `Cargo.toml`:

| Where | Library | Version |
|---|---|---|
| `contract/`, `mock-usdc/` | `near-sdk` | 5.30.0 |
| `contract/`, `mock-usdc/` | `near-contract-standards` | 5.30.0 |
| `contract/`, `sandbox/` | `base64` | 0.22 |
| `contract/` | `serde` | 1 |
| `contract/`, `sandbox/` | `serde_json` | 1 |
| `sandbox/` (tests only) | `near-sandbox` | 0.4.0 |
| `sandbox/` (tests only) | `near-api`, `near-api-types` | 0.8.0 |
| `sandbox/` (tests only) | `tokio` | 1 |
| `sandbox/` (tests only, to sign test tokens) | `rsa` | 0.9 |
| `sandbox/` (tests only) | `sha2` | 0.10 |
| `sandbox/` (tests only) | `rand` | 0.8 |
| `scripts/`, `relayer/`, `agent/` (Python) | `cryptography`, `certifi`; the rest is the standard library | as installed |

Tools: Rust with the `wasm32-unknown-unknown` target and `cargo-near` 0.22.0 (`scripts/codespace-setup.sh`); the testnet steps use [near-cli-rs](https://github.com/near/near-cli-rs). Services: NEAR testnet, NEAR Chain Signatures on testnet, Solana devnet and GitHub Actions' OIDC tokens.
