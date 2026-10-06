# Drills on the deployed programs

Written by `scripts/drills.py` on 2026-10-04 05:17 UTC. Do not edit: run the command at the end.

Each row is a safety path of the second deployment, run on the bytes the cluster runs. The script reads both programs from devnet with `getAccountInfo`, loads exactly those bytes into LiteSVM (a simulator inside the script's process) at their real ids, and moves the simulator's clock. No transaction is sent to a cluster, so a row is a log of the deployed code, not a transaction a block explorer can show. The last four rows are the upgrade drill, which this script does not run: `scripts/drill_upgrade.sh` runs it against a validator on the machine it is run on, with the real Squads program.

14 of 15 rows passed, 0 failed, 1 were not run.

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
| second operator | a second person, their own machine |  | not run: not yet run by a second person (docs/OPERATOR.md, "The drill", says who runs it and when it passes) |
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

- **a second person, their own machine**: no script runs this row. Someone who is not the founder follows [OPERATOR.md](OPERATOR.md) from a clean clone, and the row passes when a transaction their own relay key sent has paid or refunded one devnet order. Nobody has done it yet.

Money in the rows without tokens is a 6-decimal SPL Token mint made in the simulator, standing in for test USDC. The rows with tokens use the program's own faucet mint.

## When a dependency fails

These rows are of another kind than the ones above. Each breaks one thing Knos depends on and follows a payment through it. They need a token signed for every step, and nothing but GitHub can sign one the deployed programs take, so they run the programs' test builds (`knos_oidc` `1c7c7af6ca85f2c5e49aa69516069e5bd47a63328968d644703fb6d196ebc1ee`; `knos_pay` `325e699ccab376493d2b3f04a66f5140747407afc54c312e48a542a84f1b31db`: the same source built with a key this repository holds) in LiteSVM, with the relay's own code and the fakes of GitHub and of the RPC endpoint that the tests use. Seconds are the simulator's: the drill moves the clock, and the relay makes a pass every 3 s as the public worker does. No cluster and no GitHub is touched, and none of these failures has been rehearsed on devnet.

7 of 7 rows passed, 0 failed, 0 were not run.

| Failure | What was broken | What the customer sees | How it recovers | Measured recovery, simulated seconds | Result |
|---|---|---|---|---|---|
| GitHub's API is down for ten minutes | every request the relay made to GitHub answered 502 for 600 s; three merged pull requests had their proof tokens posted just before | the pull request is merged and no payment comment appears; `knos bounty` still shows the money in escrow | nothing to do. The relay asks again every 3 s; a token is good for an hour past its expiry, so an outage under an hour loses none. Longer than that: run the workflow again (`/knos settle`) for a fresh token | all 3 paid on the first pass after GitHub answered, 3 s later (603 s after their comments); none paid twice in the passes that followed | pass |
| GitHub's signing key has expired on chain | the verifier's 30 days for the key GitHub signs with ran out (no refresh landed); a second key of GitHub's was still good | a merged pull request is not paid, and the relay's log says why before any fee is spent (no transaction was sent): the token cannot be verified: this signing key expired 2026-10-21 14:13 UTC: nothing attested it for 30 days. Run the rotate workflow and send Refresh with its token. | anyone refreshes the key: a run of the pinned rotate workflow in which GitHub names the key, verified under a key that is still good, then `Refresh` (drills_recovery.md, case C). The proof that was refused is then paid; nothing is signed again | paid 121 s after the key expired: the refresh was sent 120 s in, by a key that holds nothing, and the same token paid on the next send | pass |
| the relay is killed between a send and its confirmation | the relay's process ended after the paying transaction landed and before it noted or logged anything (its notes said the token was being sent) | the money arrives; the payment comment is late by one pass of the relay | nothing to do. The token was written to the relay's notes before it was sent, so the next pass (or the next run) sends it again; the chain's single-use marker answers that it is done, nothing moves twice, and the log gets its line | answered 3 s after the kill (3 s of passes); the payee holds 4.875 once, after two sends of the same token | pass |
| the RPC endpoint errors and returns stale blockhashes | for 60 s every transaction the relay sent failed: a closed connection, or "Blockhash not found"; reads still answered | the payment comment is late; nothing says "failed", because the failure says nothing about the token | nothing to do. The relay tries the token again on its next pass, then after 10, 20, ... 60 s, and every 60 s from then while the chain would still take it; a failure of the endpoint never ends a token | paid 12 s after the endpoint answered again, on try 6 (tries at 3, 6, 9, 21, 42, 72 s); paid once | pass |
| the evidence is missing (a required check run was deleted) | the bounty's terms require the checks `build` and `test` at the merged commit; GitHub no longer lists `test` there | one comment on the pull request: "Knos: not paid.", each required check with what GitHub shows (`test`: did not run on this commit), and what to do. No token is signed, so no relay and no program is asked to pay | run the check again on that commit and comment `/knos settle` (anyone may); or a maintainer pays with `/knos tip`. Otherwise the money goes back to the funder at the deadline | refused by the job the merge started, after 0 s of waiting (a check that is absent is not waited for); paid 30 s after `/knos settle`, once the check was back | pass |
| devnet is reset | the cluster lost every account: the programs, every order and Balance, every binding and signing key, and the test USDC itself | `knos status` says the programs are not deployed; open orders are gone and cannot be refunded (it was test USDC from a faucet); explorer links to old transactions stop working | what was accepted and paid stays provable: `knos bundle verify FILE --mirror DIR` and `knos receipt verify ORDER --mirror DIR` check the saved bundle and the mirrored receipt with no cluster. A funder waits until `knos status` passes again, then funds anew (drills_recovery.md, case A) | 0 s for the record: 9 checks of the bundle and the mirror's receipt passed with the chain gone. The orders are not recovered: redeploying is by hand and was not timed | pass |
| devnet is reset and the operator's copies are deleted | the cluster lost every account, and the working copy (the vault folder with every sealed bundle) was deleted. One file is left: the plain archive `knos vault export` wrote, kept by the customer | nothing from Knos answers: no cluster holds the payment and no operator holds the evidence | `knos vault restore knos-evidence.tar --to DIR` writes every bundle back, each checked against the archive's checkpoint; `knos bundle verify --no-chain --no-network FILE` then passes on every receipt, from the issuer's signature and the archived copy of the chain record inside the bundle ([VAULT.md](VAULT.md)) | 0 s for the record: 1 of 1 bundle restored byte for byte from the export alone, 14 statements sorted with no chain and no network, the checkpoint's root recomputed. The test chain holds one order, so one bundle; the open orders and the money are not recovered | pass |

These rows alone, with no cluster: `python scripts/drills.py --dependencies-only` (it rewrites this section, and appends the hand-written half of the page anew). What each means for someone who is waiting for a payment is at the end of this page.

## Reproduce

```
pip install -e '.[dev]'
npm ci --prefix scripts
KNOS_DRILL_LOG=docs/drill_upgrade.log bash scripts/drill_upgrade.sh --from-devnet
python scripts/drills.py --rpc https://api.devnet.solana.com --tokens tokens.jsonl --upgrade-log docs/drill_upgrade.log
```

The script exits 1 when a row fails. With `--strict` it also exits 1 when a row it can run was not run.

## Recovery a funder can run

This section is written by hand and kept in `docs/drills_recovery.md`; `scripts/drills.py` appends it to the table
above. The rows above show that the safety paths work on the deployed bytes. This section is the other half: what
a **funder** does, step by step, in three failures, using only a Solana key of their own and public commands.

What has and has not been rehearsed: every instruction named below is run by the tests named beside it, in a
simulator. The refund of a bounty has also run on the deployed bytes (rows 1 and 2 above). The table "When a
dependency fails" above walks a payment through seven failures, also in a simulator, on the programs' test builds.
**No funder outside Knos has run any of these steps, and none of these failures has been rehearsed on devnet.** The rows above ran on the bytes deployed
on the day the table was written (0.3.12's); work orders, `RefundOrder` and `Cancel` are live only once the 2.1
upgrade of 0.3.14 has executed ([`web/upgrades.json`](../web/upgrades.json)).

In every case, first see where you stand:

```
pip install knos                 # from PyPI: needs nothing of GitHub's
knos status                      # the programs, their upgrade authority, every signing key and its expiry, pending upgrades
knos bounty OWNER/REPO#ISSUE     # what is in escrow for an issue
```

To send anything you need a Solana key with a little devnet SOL, and an RPC endpoint (`KNOS_RPC`; the default is
the public devnet endpoint). You never need a key of Knos's, and no step below asks Knos for anything.

### A. Devnet is reset

Solana's devnet "may be subject to ledger resets" ([Solana's documentation](https://solana.com/docs/references/clusters)).
A reset removes every account: the programs, the multisigs, every order, Balance, binding and signing key, and the
test USDC itself.

1. **Notice it.** `knos status` says the programs are not deployed, and `knos bounty` finds nothing.
2. **Nothing can be recovered, and nothing of value is lost.** The money was test USDC from a faucet. There is no
   refund to send, because there is no account to refund from.
3. **Keep your own record.** What was accepted and paid before the reset is no longer on chain. `knos export`,
   `knos statement` and the receipts you saved are the only record; a devnet explorer link to an old transaction
   stops working.
4. **Wait for the programs to be deployed again.** That is Knos's job: the same program ids, the multisigs made
   again, GitHub's keys registered again. `knos status` passes when it is done. Until `knos status` shows the
   upgrade authority is the multisig's vault again, do not fund.
5. **Fund again,** by comment or from a wallet. Old orders do not come back; an issue that was funded is funded
   anew, with new terms and a new deadline.
6. **A payee** binds a wallet again (the claim workflow, by hand); the old binding went with the ledger.

This failure exists only on devnet. It is the reason nothing on devnet should be treated as a durable record.
*Rehearsed:* a deployment from nothing is what `tests/test_deploy_v2.py` checks of `scripts/deploy_v2.sh`. *Not rehearsed:* a
reset. None has been walked through with the steps above.

### B. The relay's GitHub account is suspended

The public relay, the published workflows and the rotate workflow are in repositories of one personal GitHub
account ([GOVERNANCE.md](GOVERNANCE.md), section 9). If GitHub suspends it, comments stop being answered, no new
token is signed for an order that pinned the published workflows, and nobody carries tokens to the chain.

1. **Notice it.** A `/knos` comment gets no reply; the repository's Actions tab shows the Knos job failing to
   start because the workflow it calls cannot be found; the site does not load. `knos status` still works: it reads
   the chain.
2. **If only the relay has stopped** (the workflows still run and post their tokens as comments): relay them
   yourself. `KNOS_RELAY_KEY=<your key file> knos relay` makes one pass over the posted tokens and pays the
   transaction fees; a payment tips whoever relays it. Nothing else is needed, and you can stop here.
3. **If the workflows cannot run,** an order that pinned them can no longer be paid. Take your money back:
   - **Unspent money in a Balance:** `knos balance withdraw <the GitHub owner>` (or the Balance panel of a
     copy of the site), signed by the wallet that opened it. At once.
   - **An order you funded from a wallet:** your wallet signs `Cancel`. The deadline becomes at most 7 days away.
     There is no `knos` command for this yet: `knos.settle.v2.pay.cancel_ix` (Python) and `cancelIx` in
     `sdk/settle/index.js` build the instruction. Or do nothing and wait for the order's own deadline.
   - **An order funded from a Balance by comment:** it cannot be cancelled, because that needs a token. Wait for
     its deadline.
   - **After the deadline, for either:** `KNOS_RELAY_KEY=<your key file> knos relay` sends `RefundOrder` for every
     order that is due. Anyone's key will do. The amount and the fee go back to the wallet or the Balance they came
     from; then withdraw the Balance as above.
4. **Check it.** `knos bounty OWNER/REPO#ISSUE` shows nothing in escrow, and your wallet's token account holds the
   amount and the fee again.
5. **What you cannot recover.** Work a seller delivered and you merged but that was not yet paid is not paid by the
   program: settle it with the seller directly. A holdback in its warranty cannot be reverted (that needs a token);
   after the warranty anyone can send `Release` and it goes to the seller.
6. **Within 30 days** every signing key expires, because the refresh also depends on that account (case C).

*Rehearsed in tests:* relaying by anyone, `test_a_token_relayed_twice_or_by_two_relayers_is_done_once`; the refund
by a stranger, `test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before`; cancellation with notice,
`test_a_reservation_a_cancellation_with_notice_and_the_kill_fee`; the withdrawal,
`test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance`. *Not rehearsed:* a real suspension.
Nobody has pointed a repository at workflows that cannot be fetched and walked these steps on devnet.

### C. The key refresh is missed

Every signing key in the verifier expires 30 days after it was last attested. If no refresh lands, tokens under an
expired key are refused: no funding by comment and no payment.

1. **Notice it early.** `knos status` fails when any key has less than 7 days left and names the key. Run it on a
   schedule if you hold open orders.
2. **Refresh it yourself, while the 2.1 verifier is live and the rotate workflow can be fetched.** In a repository
   of your own personal GitHub account, add a workflow that calls
   `drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml` at the commit `rotate_sha2` of
   [`programs-v2/program_ids.json`](../programs-v2/program_ids.json), with `id-token: write`, and start it by hand.
   It asks GitHub for a token that names each key GitHub still publishes. Carry that token with
   `knos relay --token-file <file>`: the verifier's `Refresh` moves each key's expiry to 30 days from now. Your run
   can refresh a key. It can never add one.
3. **If a key has already expired** and another is still usable: the same steps. An expired key is refreshed by an
   attestation verified under a key that is not.
4. **If every key has expired,** nothing can be verified, so nothing can be refreshed. Then only refunds work:
   follow case B, step 3. The way back for the system is an upgrade of the verifier through the multisig, public
   for 48 hours; a funder cannot do it.
5. **Check it.** `knos status` lists every key with its new expiry.

*Rehearsed:* the row "a key is refreshed" above (real GitHub tokens, the deployed bytes) and "a key expires after 30
days"; refresh from a repository of one's own,
`test_anyone_refreshes_a_key_from_a_repository_of_his_own_and_nobody_registers_one_that_way`; a token refused while
its key is expired and accepted again after a refresh,
`test_a_token_is_refused_while_its_key_is_expired_and_works_again_once_the_key_is_refreshed`. *Not rehearsed:* a
refresh on devnet by an account other than Knos's; and the state with every key expired, on a cluster.

### D. Knos's operator is gone, and devnet with it

What you need beforehand: an export archive (`knos vault export`, [VAULT.md](VAULT.md)) kept somewhere of your own,
and the `knos` package. Nothing else.

```
knos vault restore knos-evidence.tar --to restored
knos vault verify restored/CHECKPOINT.json --against restored
knos bundle verify --no-chain --no-network restored/<file>
```

The first writes every bundle back and checks each against the archive's checkpoint. The second recomputes the
checkpoint's root; compare it with the line you wrote down when the archive was made. The third, for each bundle,
sorts every statement of the receipt into verified from the issuer's signature, resting on the archived copy of
the chain record, or not checkable without a cluster. What is not recovered: open orders and the test USDC in them.
The drill is the row "devnet is reset and the operator's copies are deleted" above; no customer has done it with
an archive of their own.

## What you see when something Knos depends on fails

For a funder or a payee who is waiting, not for an operator. Each case is a row of "When a dependency fails" above:
it was run in a simulator, on the programs' test builds, with a fake GitHub and a fake RPC endpoint, and the seconds
are the simulator's. None has been rehearsed on devnet, and nobody answers a page when one happens: today the
service is run by its founder alone.

First look at the relay's own account of itself. Its log is the open issue labelled `knos-relay` in
`drexthealpha/Knos`; one comment there is rewritten every minute and says when the relay last ran, how many tokens
wait and for how long, and how many it refused or retried in 24 hours. Then:

| What happened | What you see | What you do | How long it took in the drill |
| --- | --- | --- | --- |
| GitHub's API is down | The pull request is merged and no payment comment appears. `knos bounty OWNER/REPO#ISSUE` still shows the money in escrow. | Nothing. The relay asks GitHub again every 3 seconds, and a signed token is good for an hour past its expiry. If GitHub was down for more than an hour, comment `/knos settle` on the pull request: a fresh token is signed. | All three waiting payments were paid 3 s after GitHub answered again, none twice. |
| The key GitHub signs with has expired on chain | No payment, and the relay's log line says `this signing key expired ...: Run the rotate workflow and send Refresh with its token`. No fee was spent on the refusal. | Anyone can refresh the key (case C above). Then the same token is paid: nothing is signed again, as long as the refresh lands within the token's hour. | Paid 121 s after the expiry, the refresh having been sent 120 s in by a key that held nothing. |
| The relay was stopped in the middle of your payment | The money arrives. The payment comment is a few seconds late. | Nothing. The token was written down before it was sent; the next pass sends it again and the program, which takes a token once, answers that it is done. | Answered 3 s after the stop; the payee held the payment once after two sends. |
| The RPC endpoint errors, or its blockhashes are stale | The payment comment is late. Nothing says "failed": the failure says nothing about your token. | Nothing. The relay tries again after 3 s, twice, then 10, 20, up to 60 s apart, for as long as the token is good. | Paid 12 s after the endpoint answered again, on the sixth try; once. |
| The evidence is missing: a check the terms require is no longer on the merged commit | One comment: `Knos: not paid.`, each required check with what GitHub shows for it, and what to do. No token is signed, so nothing can be paid by mistake. | Run the check again on that commit and comment `/knos settle` (anyone may). A maintainer can pay the work anyway with `/knos tip <amount>`. Otherwise the money goes back to the funder at the deadline. | Refused by the job the merge started; paid 30 s after `/knos settle` once the check was back. |
| Devnet was reset | `knos status` says the programs are not deployed. Open orders are gone; it was test USDC. Explorer links to old transactions stop working. | Keep proving what was paid: `knos bundle verify FILE --mirror DIR` and `knos receipt verify ORDER --mirror DIR` check a saved bundle and the mirrored receipt with no cluster. Then case A above: wait until `knos status` passes again, and fund anew. | The bundle and the mirror's receipt verified with the chain gone, at once. The orders are not recovered; redeploying is by hand and was not timed. |
| Devnet was reset and Knos's own copies are gone | Nothing from Knos answers: no cluster holds the payment, and no operator holds the evidence. | Restore from the archive you kept: `knos vault restore knos-evidence.tar --to DIR`, then `knos bundle verify --no-chain --no-network FILE` for each bundle (case D above). | The one bundle of the drill was restored byte for byte and its receipt verified with no chain and no network, at once. Open orders and their test USDC are not recovered. |

What these rows do not cover: GitHub's Actions being down (no workflow runs, so no token is signed: wait, or use
case B), a relay that never starts again (relay it yourself: `KNOS_RELAY_KEY=<your key file> knos relay`), and
mainnet, which Knos has never touched.
