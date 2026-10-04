## Recovery a funder can run

This section is written by hand and kept in `docs/drills_recovery.md`; `scripts/drills.py` appends it to the table
above. The rows above show that the safety paths work on the deployed bytes. This section is the other half: what
a **funder** does, step by step, in three failures, using only a Solana key of their own and public commands.

What has and has not been rehearsed: every instruction named below is run by the tests named beside it, in a
simulator. The refund of a bounty has also run on the deployed bytes (rows 1 and 2 above). **No funder outside Knos
has run any of these steps, and none of the three failures has happened.** The rows above ran on the bytes deployed
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
