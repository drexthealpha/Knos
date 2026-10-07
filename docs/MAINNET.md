# From devnet to mainnet: the gates

**Mainnet is not planned for this release, and nothing in this release touches it.** Every program id in
[`programs-v2/program_ids.json`](../programs-v2/program_ids.json) is a devnet id, every released binary is a devnet
build, and all money is test USDC. This page is the list of what must be true first. The gates are conditions, not
dates: none has a day attached, and a gate is passed only when its evidence exists where the last column says.

The count, the statement and the controls do not depend on mainnet: they are software that would be invoiced off
chain ([MARKET.md](MARKET.md)), and none has been sold. Only settlement in real money needs what follows.

## The gates

| # | Gate | Passed when | Today |
|---|---|---|---|
| 1 | The two adversarial findings are fixed | the `knos_pay` build that fixes them runs on the public devnet ids, and the two tests in [`adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs) pass without `--ignored` | open: both pass on the build of this tree, which is proposed after the release and is not live at the public ids until it executes ([SECURITY.md](SECURITY.md), "Two findings") |
| 2 | Outside key holders | `outside` in [`web/keyholders.json`](../web/keyholders.json) is not empty, after the proposal that adds the key executed on chain, and one person can no longer meet the threshold alone | 0 outside holders; all member keys are the founder's ([KEYHOLDER.md](KEYHOLDER.md), [GOVERNANCE.md](GOVERNANCE.md)) |
| 3 | Verified builds reproduced by someone else | a report from a machine that is not the founder's shows the on-chain bytes hashing to the verified build ([REPRODUCE.md](REPRODUCE.md), [ASSURANCE.md](ASSURANCE.md)), and a capability stands at `reproduced` | nobody outside has done it |
| 4 | An outside security review | `docs/review.json` names a reviewer, a report at an https address, the commit, and the executable hashes reviewed, and those hashes are the bytes on chain | none; `knos mainnet-check` fails on this line on purpose |
| 5 | A legal entity, and legal advice on escrow and money transmission | the five points of [REGULATION.md](REGULATION.md), "Before real money", each have a written answer | no entity; no lawyer has read it |
| 6 | An incident and upgrade policy | the policy below is published as binding, with a contact that answers, and has been drilled once by someone other than its author | written here as a draft; the drill has not been run ([OPERATOR.md](OPERATOR.md)) |
| 7 | A staged cap on order size | the mainnet build's cap is a constant in its source, starts low, and the rule for raising it is published before the first order | not decided |
| 8 | The mainnet build itself | new program ids, a build without the `devnet` feature, the same verified-build and upgrade-gate records as devnet, behind the same multisig and delay | does not exist |

The order matters in two places. Gate 1 comes before gate 4, so that the review is of the programs meant to hold
money and not of ones with known defects. Gates 2 and 4 come before the verifier is frozen
([GOVERNANCE.md](GOVERNANCE.md), section 7).

## What changes in the programs for real USDC

Checked against the source in `programs-v2/` on 2026-10-06.

**The mint: nothing.** `knos_pay` does not fix one mint. Money enters in any SPL Token mint, or a Token-2022 mint
whose every extension is on the allowed list ([SECURITY.md](SECURITY.md), section 11). Circle's mainnet USDC mint
is already a constant beside the devnet one (`USDC_MAINNET`, `USDC_DEVNET` in
[`knos_pay/src/lib.rs`](../programs-v2/knos_pay/src/lib.rs)), and the public record already counts a payment as
real money only in those two (`counted`). `knos_meter` takes credits only in the same two mints (`FEE_MINTS`).

**What does change.**

- **The build feature.** The default feature is `devnet`; it enables the test-USDC faucet. A build for real money
  is made with `--no-default-features`, and both faucet instructions then refuse (error 89, "devnet builds only";
  [`Cargo.toml`](../programs-v2/knos_pay/Cargo.toml), `fund.rs`).
- **The addresses compiled in.** Each program names the others by id (`OIDC_ID` in `knos_pay` and `knos_meter`,
  `KNOS_PAY` in `knos_passkey`). `knos_oidc` pins the guardian and the commit of the rotate workflow; `knos_pay`
  pins the fee owner and the commit of the claim workflow. New program ids mean new constants and so new bytes: a mainnet
  build is a different binary and needs its own verified-build record. An address is derived from the program id,
  so a token for one cluster names nothing on the other; `knos mainnet-check` already checks that the devnet ids
  are in use on no other cluster.
- **The cap.** `MAX_AMOUNT` is 100,000 whole units per order, a devnet number written in the source. A mainnet
  build decides its own (gate 7).
- **The multisig program.** On devnet the Squads program is itself upgradeable; on mainnet it has no upgrade
  authority ([SECURITY.md](SECURITY.md), section 7). The time lock and the absence of a config authority are
  re-created and re-checked, not carried over.

**Outside the programs.** The relay pays fees in real SOL and may need priority fees, which no measurement here
includes ([MARKET.md](MARKET.md)). The faucet and the playground exist only on devnet.

## A staged cap

Not decided; this is the shape intended. The first mainnet build carries a low per-order cap as a constant. Raising
it is a program upgrade like any other: proposed through the multisig, public for 48 hours, with the new bytes
verifiable before the vote. The rule for when a raise may be proposed (how long at the current cap, how much
settled, no open incident) is published before the first order, so that a raise is the execution of a rule and not
a judgement made on the day. A funder's own Balance limits (per order, per day, in total) stay available below the
program's cap.

## Incident and upgrade policy (draft)

What exists today is the mechanism; what is missing is the commitment and the people.

- **Upgrades.** Only through the upgrade multisig, 2 of 3, executable 48 hours after approval and not before. The
  proposal and the new program's bytes are public for those 48 hours ([GOVERNANCE.md](GOVERNANCE.md), sections 1 to
  3). A key holder's four checks before a vote are in section 4 there.
- **Stopping.** The guardian multisig can revoke a signing key and can pause new funding for at most 7 days. A
  pause does not stop a refund, a withdrawal or a payment already owed ([KEYHOLDER.md](KEYHOLDER.md)).
- **No fast path.** There is no upgrade without the delay. A defect found in a running program is answered by a
  pause, a public proposal and 48 hours. [GOVERNANCE.md](GOVERNANCE.md), section 3, is the one time this has
  happened: a defect found during the delay, and the proposed build replaced before it ran.
- **Reporting.** `SECURITY.md` at the repository's root and the `security.txt` in each binary name the contact.
  Every incident is written up in the open with what was affected and what changed.
- **Recovery without Knos.** Refunds need neither GitHub nor Knos ([SECURITY.md](SECURITY.md), section 10;
  [DRILLS.md](DRILLS.md)).
- **Missing for gate 6.** Response times anyone is held to; a second person who can act; a drill of this policy
  run by someone who did not write it.

## What `knos mainnet-check` verifies today

The command ([`src/knos/mainnet_check.py`](../src/knos/mainnet_check.py)) reads the devnet deployment and prints
each line with the evidence it was judged on. It exits 1 while any line fails.

| Line | What it checks |
|---|---|
| verified build | for `knos_oidc` and `knos_pay`, the on-chain bytes hash to this repository's verified build |
| upgrade authority | each program's upgrade authority is the pinned vault, or none |
| security.txt | each on-chain binary embeds one |
| new programs | `knos_meter` and `knos_passkey`, once deployed, are executable and held to the same vault |
| upgrade multisig | the pinned vault is vault 0 of the pinned Squads multisig; its time lock is 172,800 seconds; it has no config authority |
| guardian | the guardian both programs name is the pinned guardian multisig's vault, which has no config authority |
| workflow pins | the rotate and claim commits are in the on-chain binaries and exist on GitHub |
| GitHub's keys | every key GitHub publishes today has a key account that verifies now |
| other clusters | the program ids are in use on no other public cluster |
| program checks | the last `program.yml` run on main passed: Wycheproof vectors, the differential test, property tests, fuzz walks, cargo-audit |
| outside review | `docs/review.json` records one, of the bytes on chain. There is none: this line fails |
| mainnet | locked, by design, until every line above passes |

**What it does not check.** Gates 1, 2, 3, 5, 6 and 7 of this page. It does not read who holds the member keys, it
does not know whether anyone outside reproduced a build, and nothing about law or policy is in it. Passing
`knos mainnet-check` is necessary and is not the decision to deploy. A line it cannot ask from where it runs is
shown as SKIP and is not a pass.
