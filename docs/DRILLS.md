# Drills on the deployed programs

Written by `scripts/drills.py` on 2026-10-04 05:17 UTC. Do not edit: run the command at the end.

Each row is a safety path of the second deployment, run on the bytes the cluster runs. The script reads both programs from devnet with `getAccountInfo`, loads exactly those bytes into LiteSVM (a simulator inside the script's process) at their real ids, and moves the simulator's clock. No transaction is sent to a cluster, so a row is a log of the deployed code, not a transaction a block explorer can show. The last four rows are the upgrade drill, which this script does not run: `scripts/drill_upgrade.sh` runs it against a validator on the machine it is run on, with the real Squads program.

14 of 14 rows passed, 0 failed, 0 were not run.

## The programs

| Program | Address | ProgramData account | sha256, trailing zeros trimmed | Upgrade authority | Deployed in slot |
|---|---|---|---|---|---|
| `knos_oidc` | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | `9tqAQLKPvthKcdj1Tk9bPDPGNWesPK39bS6q4atoRiLw` | `71f8fe068c94ce69262e7fa250f65fc149334d60f6742ad66ac6b91624c0d1df` | `CKCrTBN542pVhizxuSPVg8tvdnPooNxt9B7o97VuTjz2` | 507037733 |
| `knos_pay` | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | `9GaiLgcz6y1dqKRo3KygEhiRavi9juLLHENyHLARPcFp` | `75d7eb959f75575f6816942ad18a97c93a01690782e2b82ce01d7823c94e0a69` | `CKCrTBN542pVhizxuSPVg8tvdnPooNxt9B7o97VuTjz2` | 507037816 |

The hash is the one `solana-verify get-program-hash` prints, and the one [ASSURANCE.md](ASSURANCE.md) says how to compare with a build of this repository's source.

## The drills

| Drill | Signatures | What was checked | Result |
|---|---|---|---|
| refund only after the deadline | keys made here | a wallet funded 20 for 14 days; Refund sent by a stranger is refused on day 0 and in the deadline's own second (error 83) and to another token account (88); one second later it returns all of it to the funder and closes the job; a second refund finds no job | pass |
| a held payment returns after 180 days | held state written | a funded job of 20 marked held for a payee with no wallet; Refund is refused past the work deadline and in the last second of the 180 days (error 83); one second later all of it is back with the funder and the job is closed | pass |
| only GitHub's four keys without an attestation | keys made here | RegisterKey with no attestation takes exactly the four GitHub keys pinned on 2 Oct 2026, each once (a second time: error 67); GitLab's keys (6 tries) and a GitHub key under GitLab's name are refused (73) | pass |
| a key expires after 30 days | keys made here | a genesis key registered at 2026-10-04 05:17 UTC expires exactly 30 days later; the verifier works with it on day 0 and in its last second (an unsigned token is stepped, then refused as not GitHub's, error 70); from its expiry on the first step is refused (77), a year later too, and it cannot be registered again | pass |
| the guardian's pause lapses after 7 days | authority simulated | Pause is refused from a stranger, from the guardian's address without its signature and from another vault (error 97), and for more than 7 days (81); the guardian's 7-day pause refuses FundWallet (96) to its last second while a refund still goes through; at 7 days funding works again with no further instruction | pass |
| nobody but the guardian revokes | authority simulated | Revoke is refused from a stranger, from the guardian's address without its signature and from another vault (error 79), and the key goes on verifying; the guardian's Revoke ends it: the first step is refused (78), Approve and RegisterKey do not bring it back, and 31 days later it is still refused as revoked | pass |
| a key is refreshed | real GitHub tokens | a key registered 2026-09-22 09:13 UTC would expire 2026-10-22 09:13 UTC; the rotate workflow's token issued 2026-10-02 09:13 UTC (drexthealpha/knos-oidc-rotate) is verified and Refresh moves the expiry to 2026-11-01 09:13 UTC; the same token an hour past its own expiry is refused (75) | pass |
| a payment | real GitHub tokens | the fund token of drexthealpha/knos-e2e issue 36 (issued 2026-10-03 16:19 UTC) opened a job of 5 test USDC from the faucet; the pay token issued 2026-10-03 16:20 UTC was verified in 2 steps and paid it: held for GitHub user 142920951 until 2027-04-01 16:20 UTC (the proof names no wallet and none is bound here) | pass |
| a replay is refused | real GitHub tokens | after the payment both tokens are verified again (the verifier keeps no memory) and sent to the escrow once more: the pay token again: error 83; the fund token again: error 91; no money moved | pass |
| a token under a revoked key is refused | real GitHub tokens; authority simulated | the fund token of drexthealpha/knos-e2e is verified; the guardian revokes the key that signed it; the escrow then refuses that verified token (error 78: no test USDC is minted, no job is funded) and the verifier refuses to verify it again (78) | pass |
| an upgrade is proposed | the multisig's vote, local validator | on a local validator that holds, copied from https://api.devnet.solana.com, the bytes of both programs as deployed, the Squads program and both multisig accounts, each member's key replaced by a key made for the drill: the bytes knos_pay already runs, in buffer FRBNMB5RCMVXCNLsSW4Qa73cdkb9dEeyR3hFCAwg2isX owned by the vault; proposal 1 of the upgrade multisig is approved and can be executed from 2026-10-06 04:57:25 UTC, 48 hours after the vote; governance.mjs refused it first because the upgrade gate holds no record of these bytes (deployed before the gate existed), so it was proposed with --ungated | pass |
| no upgrade before 48 hours | the multisig's vote, local validator | at 2026-10-04 04:57:59 UTC governance.mjs refuses to execute proposal 1; sent anyway, the Squads program refuses it (TimeLockNotReleased); knos_pay is unchanged (slot 0) | pass |
| an upgrade after 48 hours | the multisig's vote, local validator | at 2026-10-06 21:23:24 UTC proposal 1 is executed by the Squads program: knos_pay was deployed again in slot 579048 (before: 0) with the same executable hash 75d7eb959f75575f6816942ad18a97c93a01690782e2b82ce01d7823c94e0a69, and its upgrade authority is still the vault | pass |
| a cancelled upgrade never runs | the multisig's vote, local validator | proposal 2 was approved, then cancelled by the members' votes; governance.mjs refuses to execute it and, sent anyway, the Squads program refuses it (InvalidProposalStatus) before its 48 hours and after them; knos_pay is unchanged (slot 579048). Its buffer F4BjidbEnH9qmWM1RZ4ou4z4szKzPbTUFgawfrhUDmQf stays with the vault | pass |

## What the second column means

- **keys made here**: every signature is a real one, by a key the script made. These drills use only instructions that anyone may send.
- **authority simulated**: the guardian (`AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc`) is the vault of a Squads multisig. It has no private key: on a cluster it signs only by a cross-program call from the Squads program, after the members' vote. The script turns the simulator's signature check off for that one transaction and names the vault as a signer. The program under test sees the same signer flag either way; the multisig's vote is not exercised here (`scripts/drill_upgrade.sh` and `scripts/governance.mjs` do that against the real Squads program). The same switch is used to show that another vault, signing, is refused.
- **held state written**: a job is held only after a GitHub-signed proof for a payee with no wallet. Without a token the script funds a job through the program and writes the three fields `Pay` writes when it holds one (state, payee, hold time) into the job's account. The refusals and the refund are the deployed program's.
- **real GitHub tokens**: tokens GitHub signed, read from a file with GitHub's key set of their day, carried by the same relay code the public worker runs, with the simulator's clock at each token's issue time. This run read 106 tokens from `tokens.jsonl`.

- **the multisig's vote, local validator**: `scripts/drill_upgrade.sh`, on a validator on the machine it is run on, which holds the real Squads program and both multisigs. The upgrade is proposed, approved, executed and cancelled by member keys through the Squads program, with `scripts/governance.mjs`; the validator's clock is moved 48 hours. The first of these rows says what that validator held: with `--from-devnet`, devnet's bytes of both programs and both multisig accounts, each member's key replaced by a key made for the drill (the members' real keys are not used). This run read those rows from `docs/drill_upgrade.log`.

Money in the rows without tokens is a 6-decimal SPL Token mint made in the simulator, standing in for test USDC. The rows with tokens use the program's own faucet mint.

## Reproduce

```
pip install -e '.[dev]'
npm ci --prefix scripts
KNOS_DRILL_LOG=docs/drill_upgrade.log bash scripts/drill_upgrade.sh --from-devnet
python scripts/drills.py --rpc https://api.devnet.solana.com --tokens tokens.jsonl --upgrade-log docs/drill_upgrade.log
```

The script exits 1 when a row fails. With `--strict` it also exits 1 when a row was not run.
