## Recovery a funder can run

This section is written by hand and kept in `docs/drills_recovery.md`; `scripts/drills.py` appends it to the table
above. The rows above show that the safety paths work on the deployed bytes. This section is the other half: what
a **funder** does, step by step, in three failures, using only a Solana key of their own and public commands.

What has and has not been rehearsed: every instruction named below is run by the tests named beside it, in a
simulator. The refund of a bounty has also run on the deployed bytes (rows 1 and 2 above). The table "When a
dependency fails" above walks a payment through eight failures, also in a simulator, on the programs' test builds.
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
| GitHub signs with a new key | Nothing, if the key was admitted in time. Otherwise no payment, and the money stays in escrow. | Nothing, normally: the daily rotate run names the new key while GitHub still signs with an old one, anyone registers it, the guardian approves, and a day later it verifies. If GitHub stopped signing with every key the verifier holds first, only an upgrade of the verifier admits a key (48 hours); until then your money goes back to you at the order's deadline (`knos exit` shows when). | Paid one day after the new key was published (the program's own wait). Not admitted: never paid, refunded in full after the deadline. |

What these rows do not cover: GitHub's Actions being down (no workflow runs, so no token is signed: wait, or use
case B), a relay that never starts again (relay it yourself: `KNOS_RELAY_KEY=<your key file> knos relay`), and
mainnet, which Knos has never touched.
