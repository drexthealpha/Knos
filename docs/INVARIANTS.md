# Invariants: what holds about money and concurrency

Each guarantee below is one sentence, then the instructions that enforce it and the tests that check it. Where no
test exists the row says **no test yet**. Instruction names are those documented at the top of
[`programs-v2/knos_pay/src/lib.rs`](../programs-v2/knos_pay/src/lib.rs),
[`knos_meter/src/lib.rs`](../programs-v2/knos_meter/src/lib.rs) and
[`knos_passkey/src/lib.rs`](../programs-v2/knos_passkey/src/lib.rs); the source is the authority.

This page describes Knos 0.3.14 (`knos_pay` 2.1 as corrected, `knos_meter` 1.1, `knos_passkey` 1.1) on Solana devnet,
with test USDC. Nobody outside Knos has reviewed the programs, these statements or the tests. The tests run the
programs in a simulator (LiteSVM); [DRILLS.md](DRILLS.md) says which paths have run on the deployed bytes.
`tests/test_invariants_doc.py` checks that every test file and test name on this page exists, and
[`invariants.json`](invariants.json) is the same list for a program to read.

**The machine.** `test_a_random_machine_of_orders_tokens_and_replays_keeps_every_invariant` in
`tests/test_invariants_machine.py` checks invariants 1, 2, 3, 5, 8 and 9 together. From a fixed list of seeds it picks
one action per step among funding (from a wallet, from a Balance, by a second comment on an issue that has or had an
order), top-up, reservation, cancellation, payment, settlement, release, revert, refund, closing a marker, moving
the clock, and sending again any token it ever signed: as it was built, or against the accounts as they stand, after
giving the token's order address an order again. After every step it checks that each order gave out no more than it
took in and exactly that once closed, that no token was accepted twice, that all test USDC together is unchanged,
that a refunded order paid nobody and a paid one returned nothing, that the Balance's counters equal what was funded
from it within its limits, and that every fee is the schedule's. A failure prints its seed and step.
`test_the_machine_finds_the_double_payment_of_the_0_3_13_build_within_its_default_budget` runs the same machine on
the program as 0.3.13 built it and fails unless it finds a pay token that paid twice. The machine has no standing
orders, no kill fee, no assigned payment, one relayer and one mint; the tests named under each invariant cover those.

## What "exactly once" means here

"Exactly once" is said of an **economic operation**, never of a message, a transaction or a workflow run. The
operations are:

| operation | its identity | made once by |
|---|---|---|
| funding an order | the order's address: `["ord", scope, source, seq]` | the address can hold one order at a time, and the fund token's marker |
| paying an order | the order's address, at one funding | the order closes in the paying instruction; the pay token's marker |
| paying a standing order for one pull request | (order, pull request) | the `["done", order, pr]` marker |
| releasing or reverting a holdback | the order's address | both close the order; one runs only inside the warranty, the other only after it |
| refunding an order | the order's address | the refund closes the order |
| counting one evaluation (meter, single mode) | (work order, artifact, policy, milestone) | a marker per evaluation |
| counting one batch (meter, batch mode) | (buyer, seller, month, seq) | `seq` must equal the ledger's `next_seq` |
| a passkey withdrawal or funding | (passkey wallet, nonce) | the wallet's nonce moves on |

A token, a comment, a workflow run or a relay pass may happen any number of times. The operation they ask for
happens once or not at all.

## The invariants

### 1. An order never pays out more than was funded

An order's money is in a token account of its own (`["ov", order]`); every transfer out of it is one of the five
listed under "WHERE MONEY CAN GO" in `lib.rs`, the order is credited with exactly what its account received, and the
account is closed with the order.

- **Enforced by:** `FundOrderWallet`, `FundOrderBalance`, `TopUp` (what comes in); `PayOrder`, `SettleOrder`,
  `Release`, `RefundOrder`, `Revert` (what goes out: shares of what is left, never more). Release builds are compiled
  with `overflow-checks = true`, so an addition or subtraction that would wrap stops the transaction instead.
- **Checked by:** `test_a_random_walk_conserves_every_orders_money` and
  `test_up_to_four_payees_share_an_order_and_every_unit_is_paid` in `tests/test_order_chain.py`;
  `test_a_random_walk_over_every_promise_conserves_every_orders_money` in `tests/test_order_terms.py`; the machine
  above. The arithmetic
  alone is model-checked by the Kani harnesses in [`proofs.rs`](../programs-v2/knos_pay/src/proofs.rs), which also
  say what they assume and do not cover. The one recorded run ([`kani.json`](kani.json)) verified four of the five,
  the ones about shares, payments and conservation; the fee-bounds harness timed out and is not proved.
- **A 0.3.12 bounty** shares one vault per mint with the other bounties, so for it the guarantee is arithmetic, not
  a separate account: `Pay`, `Settle` and `Refund` move exactly the job's amount and close the job
  (`test_a_random_walk_keeps_every_vault_equal_to_its_open_jobs` in `tests/test_pay2_chain.py`).
- **Not covered:** the issuer of the token. A mint's freeze authority can freeze an order's account; no program can
  prevent that.

### 2. A milestone is never paid twice

One order is one milestone, and a standing order pays each pull request once.

- **Enforced by:** `PayOrder` closes the order in the transaction that pays it (or leaves it in WARRANTY, where no
  pay token is accepted); for a standing order it creates `["done", order, pr]` and refuses a pull request that has
  one; the pay token's own marker (invariant 3) refuses the token at any later order.
- **Checked by:** `tests/test_double_pay.py` (the case 0.3.13's build failed: fund, pay, fund the same issue again,
  send the same pay token again; and the property that no accepted token moves money a second time); the machine
  above, which reaches that case from random actions;
  `test_a_standing_order_pays_its_rate_once_per_pull_request_until_less_than_one_rate_is_left` in
  `tests/test_order_terms.py`; `test_a_proof_pays_nothing_after_the_deadline_and_no_job_twice` in
  `tests/test_pay2_chain.py`.
- **The meter** bills one (work order, artifact, policy, milestone) once:
  `test_an_evaluation_is_billed_and_counted_once_and_a_retry_is_free` in `tests/test_meter_chain.py`; a batch once,
  by its `seq`: `tests/test_meter_batch.py`.

### 3. No signed token is accepted twice by any instruction

Every instruction of `knos_pay` that takes a signed token creates the marker `["used", sha256(token signature)]`
and refuses a token whose marker exists, whatever the state of the other accounts.

- **Enforced by:** `FundBalance`, `FundOrderBalance`, `Pay`, `PayOrder`, `Revert`, `Reserve`, `Cancel` (a Balance's
  order), `Bind`, `BindOrg`. The marker records who paid its rent and the time after which no instruction accepts
  the token; `CloseMarker` returns the rent after that time and not before. [SECURITY.md](SECURITY.md), section 15,
  says how the devnet faucet's pair of instructions (`FaucetOpen`, then the funding) fits the rule.
- **Also enforced by time:** a token is refused an hour after its expiry and when dated more than five minutes
  ahead of the chain's clock, and an order accepts no token issued before the chain time of its own funding (less
  30 seconds of clock slack), so a token made for an earlier order at the same address is refused twice over.
- **Checked by:** `tests/test_double_pay.py`; the machine above, for every token it signs;
  `test_a_comment_funds_an_order_from_a_balance_once` and
  `test_a_pay_token_pays_exactly_one_job` in `tests/test_order_chain.py`;
  `test_a_used_marker_is_closed_once_no_token_it_stands_for_can_be_accepted` in `tests/test_order_terms.py`;
  `test_a_fund_token_works_once` in `tests/test_pay2_chain.py`.
- **Other programs, other mechanisms.** `knos_oidc` keeps no memory of a token: verifying one twice is harmless,
  and `RegisterKey` and `Refresh` are idempotent (a key is registered once; a refresh never moves an expiry
  earlier). `knos_meter` uses the evaluation's own key, or the batch's `seq`, in place of the signature's hash.
  `knos_passkey` takes a WebAuthn assertion, not a token, and uses a nonce
  (`test_withdrawals_follow_one_another_and_none_can_be_sent_twice` in `tests/test_passkey_chain.py`). The
  upgrade gate writes a build's record once.

### 4. A token for one order, repository, policy or deployment cannot act on another

What a token can do is fixed by the audience (`aud`) its workflow asked GitHub to sign and by GitHub's own claims,
and each instruction compares both with the account it is about to change.

| bound to | by | checked by |
|---|---|---|
| one order | the audience names the order's address (`knos3:pay`, `rule`, `revert`, `take`, `cancel`) | `test_what_a_pay_token_and_its_relayer_cannot_do` in `tests/test_order_chain.py`; `test_what_a_ruling_cannot_do` in `tests/test_order_judges.py` |
| one repository | `repository_id` and `repository_owner_id` are GitHub's claims; the order's scope hashes the repository id and the issue; ids are namespaced by issuer, so a GitLab project id is never a GitHub repository id | `test_a_comment_in_another_owners_repository_cannot_spend_a_balance` in `tests/test_pay2_chain.py`; `test_what_a_neutral_run_cannot_do` in `tests/test_order_judges.py` |
| one Balance | a fund token names the Balance's address | `test_a_fund_token_spends_only_the_balance_it_names` in `tests/test_pay2_chain.py`; `test_what_a_fund_token_cannot_do` in `tests/test_order_chain.py` |
| one set of terms (the policy of an order) | the pay token carries the hash of the terms stored at funding | `test_what_a_pay_token_and_its_relayer_cannot_do` in `tests/test_order_chain.py` |
| one policy (the meter) | the policy's hash is part of the evaluation's key | `test_an_evaluation_is_billed_and_counted_once_and_a_retry_is_free` in `tests/test_meter_chain.py` |
| one generation | audiences start `knos2:` (bounties) or `knos3:` (orders); neither path takes the other's | `test_every_audience_goes_through_one_table` in `tests/test_relay2.py` |
| one deployment | an order's and a Balance's address are derived from the program's id, so a token that names one names the program too; each deployment reads only tokens its own verifier holds | `test_a_pay_or_fund_token_of_one_deployment_is_refused_by_the_same_build_at_other_program_ids` in `tests/test_invariants_gaps.py`: the same build at a second program id refuses the first one's pay and fund tokens and takes its own. Both ids use one verifier there (a build names its verifier at compile time), so "only its own verifier's tokens" is not exercised |

Two tokens are deliberately not bound to a deployment: a **bind** token (`knos3:bind:<address>` says only "pay this
GitHub account at this address", and is true wherever it is relayed) and a **key** token (the same attestation
registers a key in both verifiers: `test_a_key_token_is_carried_to_both_deployments` in `tests/test_relay2.py`).

A **receipt** ([RECEIPT.md](RECEIPT.md)) authorises nothing. No instruction takes a receipt: it is evidence of an
acceptance, for a reader, and names the order, the commit and the terms hash it is about.

### 5. Expiry, cancel, refund and pay cannot produce two terminal states

An order ends exactly once: its account is closed by the instruction that moves the last of its money, and an
instruction sent afterwards finds no order.

- **The states:** OPEN; HELD (accepted, the payee has no wallet yet); WARRANTY (paid but for a holdback). The ends:
  paid in full (`PayOrder`, `SettleOrder`, `Release`), returned (`RefundOrder`, `Revert`).
- **Enforced by:** disjoint conditions on the chain's clock. `PayOrder` needs `now <= deadline`; `RefundOrder` needs
  `now > deadline` (OPEN) or `now > hold_until` (HELD). `Revert` runs only inside the warranty, `Release` only after
  it. `Cancel` ends nothing: once per order it moves the deadline to at most seven days away, and a pay token still
  pays until then. Solana runs transactions that write the same account one after another, never interleaved, so
  two instructions on one order see each other's result.
- **One case is not terminal:** an order cancelled while reserved, whose taker has no wallet: `RefundOrder` returns
  the rest and the order stays HELD for the kill fee alone, until the taker binds a wallet or the hold ends.
- **Checked by:** `test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` in
  `tests/test_order_chain.py`; `test_a_reservation_a_cancellation_with_notice_and_the_kill_fee`,
  `test_a_revert_inside_the_warranty_returns_the_holdback_and_its_fee_to_the_funder` and
  `test_a_holdback_stays_in_the_order_through_the_warranty_and_then_goes_to_the_wallets_it_recorded` in
  `tests/test_order_terms.py`; the two random walks of invariant 1, which send instructions in random order.
- **Every ordering:**
  `test_every_ordering_of_two_and_of_three_of_pay_cancel_expiry_refund_settle_release_and_revert_ends_an_order_exactly_once`
  in `tests/test_invariants_gaps.py` sends every ordering of two and of three of those seven moves at an order that
  pays at once, at one that is held and at one with a holdback. The chain must accept each move exactly when a model
  of a few lines does; then every clock runs out, the one instruction that still takes the order is sent, and each
  order has ended once with its money accounted for. Orderings of four and more, a standing order and a kill fee are
  in the random walks and the machine, sampled, not exhausted.

### 6. A refund stays available after the deadline with no GitHub and no Knos

After its deadline an unpaid order's whole balance, amount and fee, goes back where it came from on an instruction
that needs no token, no signature of Knos's or of the funder's, and does not read the pause.

- **Enforced by:** `RefundOrder`, which takes no token, checks only the order's state and the chain's clock, and
  pays only to the place the order recorded at funding.
- **Who can send it:** anyone with a Solana key that holds enough SOL for one transaction fee.
- **What it needs:** an RPC endpoint of the cluster; the order's address; the accounts `RefundOrder` lists (the
  order, its token account, the place the money came from, the program's `auth` address, the account the order's
  rent returns to, the mint, the token program). The destination is fixed: the Balance's own token account, or a
  token account of the mint owned by the funding wallet. If that wallet closed its token account, the sender
  creates it again in the same transaction, at their own cost. `knos relay` does all of this for every order that
  is due (`refund_orders_due` in [`relay.py`](../src/knos/settle/v2/relay.py)), with `KNOS_RELAY_KEY` set to any
  funded key.
- **Also without a token:** `Withdraw` (a Balance's wallet, at any time), `SettleOrder` (a held order whose payee
  now has a wallet), `Release` (after the warranty), `Refund` (a 0.3.12 bounty), a passkey wallet's withdrawal.
- **What can still stop it:** the mint's issuer freezing the account; no reachable RPC endpoint; a program upgrade
  that removed the instruction, which is public for 48 hours first ([GOVERNANCE.md](GOVERNANCE.md)).
- **Checked by:** `test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` in
  `tests/test_order_chain.py`; `test_an_order_is_held_for_a_payee_with_no_wallet_then_settled_and_an_unproven_one_goes_back`
  in `tests/test_relay2.py`; `test_the_guardian_pauses_new_funding_only_and_nobody_else_can` in
  `tests/test_pay2_chain.py` (a refund goes through a pause); on the deployed bytes, the rows "refund only after the
  deadline" and "a held payment returns after 180 days" of [DRILLS.md](DRILLS.md), for a bounty.
- **On the build with real-money rules:**
  `test_refund_order_on_the_committed_real_money_build_needs_no_token_no_funder_and_no_open_funding` in
  `tests/test_invariants_gaps.py` runs `RefundOrder` on `tests/fixtures/knos_pay_v2_nodevnet.so`, sent by a key that
  holds nothing but SOL, while funding is paused. That build has the rules of a real-money deployment and trusts the
  test keys; no `knos_pay` build with the real keys is committed, and the deployed bytes have still not run a
  `RefundOrder` in a drill (the drill rows refund a 0.3.12 bounty).

### 7. A retried relay has the same economic result

Relaying a token again, by the same relayer or by another, leaves the funder, the payees and the fee owner with
exactly what the first relay gave them.

- **Enforced by:** the program (invariants 2 and 3: the second transaction is refused or changes nothing), and the
  relay, which reads the chain before it sends and reports a token already carried as done, naming the transaction
  that did it.
- **What does differ:** which relayer receives the tip (the one whose transaction landed), and the transaction fee a
  relayer loses on a transaction the chain refused. A relayer's own costs are not part of the economic result.
- **Checked by:** `test_a_token_relayed_twice_or_by_two_relayers_is_done_once`,
  `test_a_token_carried_before_is_known_by_what_it_left_on_chain_and_by_nothing_else`,
  `test_a_transaction_reported_lost_that_landed_is_seen_on_the_chain` and
  `test_a_hiccup_of_the_cluster_is_tried_again_and_a_refusal_is_not` in `tests/test_relay2.py`;
  `test_a_dropped_transaction_is_tried_again_and_a_second_relayer_does_no_harm` in `tests/test_settle_relay.py`
  (the first deployment's relay).
- **In one slot:** `test_two_relayers_send_one_token_in_one_slot_and_exactly_one_is_accepted` in
  `tests/test_invariants_gaps.py`: two relayers each verify the same token and send it on one blockhash before the
  slot moves, in both orders, for a fund token and a pay token; one transaction is accepted, the tip goes to that
  relayer, and the payee is paid once. This is the simulator, which runs the two one after the other as a leader
  does; two relayers against a running validator, with its forks and retries, have not been raced.

### 8. Fees never exceed the tier schedule

The fee of an order is one pure function of its amount, `order_fee`: 2.5% of the first 1,000, 1% from 1,000 to
50,000, 0.5% above, and at least 0.40; the funder pays it on top, and nothing else is ever taken from an order.

- **Enforced by:** `FundOrderWallet` and `FundOrderBalance` take `amount + order_fee(amount)` and store the rate;
  `TopUp` takes the fee of the new amount less the fee already there; a Plan (`SetPlan`, signed by `FEE_OWNER`) can
  only lower the first tier's rate, to between 0.5% and 2.5%, until an expiry; the relayer's tip (0.05, or 0.30 on
  a payee's first payment) comes out of the fee, not on top of it; a refund returns the fee with the amount. An
  order holds at most 100,000 on devnet.
- **The minimum is a floor, so on a small order the fee is more than 2.5% of the amount:** 0.40 on an order of 5 is
  8%. The schedule, not a percentage, is the bound.
- **Checked by:** the unit tests of `order_fee` at the tier edges in
  [`lib.rs`](../programs-v2/knos_pay/src/lib.rs) and the Kani harnesses in
  [`proofs.rs`](../programs-v2/knos_pay/src/proofs.rs) (run by `cargo test` and `cargo kani`, not by pytest). The
  harness for the fee's bounds, `an_orders_fee_is_between_its_floor_and_the_first_tiers_rate_for_every_amount`, timed
  out in the recorded run ([`kani.json`](kani.json)): the bound is tested at the tier edges and is not proved for every
  amount;
  `test_a_wallet_funds_an_order_for_any_issue_and_pays_the_fee_on_top`,
  `test_only_the_fee_owner_sets_a_plan_and_only_to_lower_the_rate`,
  `test_the_orders_repository_pays_one_payee_in_full_and_the_fee_is_split` and
  `test_top_up_adds_to_the_amount_and_the_fee_from_where_the_money_came` in `tests/test_order_chain.py`.
- **The meter:** the fee of a month is the count beyond the free allowance times the rate, taken from prepaid
  Credits, and a batch that Credits cannot pay is refused whole
  (`test_the_first_ten_thousand_evaluations_of_a_month_are_free_and_credits_never_go_below_zero` in
  `tests/test_meter_chain.py`; `tests/test_meter_batch.py`).
- **Across a tier's edge:**
  `test_a_top_up_across_a_fee_tier_pays_the_difference_between_the_two_schedule_values` (to and over 1,000 and 50,000,
  and over both at once) and
  `test_a_top_up_across_the_first_tier_of_a_balances_order_keeps_the_plans_rate_below_it_and_one_percent_above` in
  `tests/test_invariants_gaps.py`. The Kani harness
  `what_a_funder_puts_in_is_what_the_payees_the_relayer_and_the_fee_owner_take_out` proves, for every amount an order
  may have at 6 decimals and every rate, that the amount and its fee are exactly what the payees, the tip and
  `FEE_OWNER` receive when the order is paid in one payment.

### 9. A Balance never spends past its limits

Money leaves a Balance by comment only within what its wallet set: a cap per order, the accounts that may spend it,
and, in its side account, a limit per day, a limit in total, the repositories and the one commit of the pinned
workflows that may spend it; and never more than it holds.

- **Enforced by:** `FundBalance` and `FundOrderBalance` (amount plus fee is counted against the limits, and the
  whole funding is refused when any is passed); `SetBalance` and `SetBalanceX` (only the wallet that opened the
  Balance changes them); `Withdraw` (only that wallet, only to itself).
- **The limits bind spending by comment.** The wallet that opened the Balance signs `TopUp` and `Withdraw` itself:
  it is the wallet's own money, and the limits are its instruction to others, not to itself.
- **Checked by:** `test_a_balance_with_a_side_account_enforces_all_of_it` in `tests/test_order_chain.py`;
  `test_a_cap_per_job_is_enforced`, `test_only_the_owner_and_the_listed_spenders_spend_a_balance` and
  `test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance` in `tests/test_pay2_chain.py`;
  `test_a_balance_with_limits_is_funded_with_its_side_account_and_refused_before_any_fee` in
  `tests/test_relay2.py`.
- **At random:** `test_a_random_walk_over_a_balances_day_and_total_counters_never_passes_a_limit` in
  `tests/test_invariants_gaps.py`: fundings, refunds, top-ups, day changes and moved limits from two fixed seeds; a
  funding is accepted exactly when a model says the day's and the total limit and the Balance's money allow it, and
  the counters equal the model's after every step. The machine above checks the same counters on its first Balance.

## What an outside system must still reconcile

The programs make each operation happen once on chain. They say nothing about a system that mirrors them. A buyer's
or a seller's own books must still reconcile these:

1. **Confirmed is not final.** The relay and the command line wait for the `confirmed` commitment. A ledger should
   book a payment when its transaction is `finalized`, and compare by transaction signature.
2. **A comment is not the payment.** The reply on GitHub is written by a workflow; the chain is the record.
   `knos receipts`, `knos statement` and `knos export` are recomputed from the programs' logs, and an outside system
   should key its entries on (order address, transaction signature), never on a comment or a run.
3. **Accepted is not paid.** A held order was accepted and has not reached the payee; after 180 days it returns to
   the funder. A holdback is paid later (`Release`) or returned (`Revert`). A standing order pays many times. Each
   is a separate entry.
4. **A refund goes where the money came from,** a Balance or the funding wallet, not to a bank account, and it can
   be sent by a stranger at any time after the deadline. The funder's books learn of it only by reading the chain.
5. **The fee and the tip** leave the order in the paying transaction: what the payees received plus the fee equals
   what the funder put in. An invoice from the seller for the same work is a second document for one payment.
6. **The meter counts what the buyer's repository ran.** The seller's own count (`ClaimBatch`) and the two off-chain
   ledgers say which events one side has and the other does not; the chain shows only that two counts differ.
7. **Devnet can be reset.** Every account then disappears, and no record on chain survives
   ([DRILLS.md](DRILLS.md), "Recovery a funder can run"). Keep exports.

## Safety and liveness

"Exactly once" is two claims, and only one of them is a guarantee.

**Safety: a payment happens at most once.** Nothing above depends on anything being up. If GitHub, every relay and
the cluster's RPC endpoints all fail in the middle of a payment, the worst outcome is that it has not happened yet;
it has never happened twice. This is what invariants 1 to 5 and 7 state and what their tests check: the machine in
`tests/test_invariants_machine.py`, and, for the moment a relay dies between sending and hearing back,
`test_a_relay_killed_after_the_chain_took_the_token_sends_it_again_and_nobody_is_paid_twice` in
`tests/test_relay_failures.py`.

**Liveness: a valid payment eventually happens.** This is not guaranteed, and no test can make it so. A payment
needs all of these to work within a window of time. Knos controls neither GitHub nor the cluster, and nobody is
obliged to run a relay:

| it depends on | for what | if it fails |
|---|---|---|
| GitHub | running the workflow, signing its token, serving the comment that carries it | no token, so no payment; a token already signed is good for an hour past its expiry |
| a relay | carrying the token to the chain (anyone may run one; none is obliged to) | nothing is sent until some relay runs |
| the cluster | an RPC endpoint that answers and blocks that are produced | the relay tries again for as long as the token is good |
| a signing key of GitHub's that is still registered on chain | the verifier takes a token only under one; a key lapses after 30 days without a refresh | the token is refused until anyone refreshes the key |
| the program as deployed | the instruction still exists and still reads this token | an upgrade can change either, after 48 hours in public ([GOVERNANCE.md](GOVERNANCE.md)) |

What is tested is recovery from named failures, in a simulator, with times that are simulated seconds: the six rows
of [DRILLS.md](DRILLS.md), "When a dependency fails" (GitHub's API down for ten minutes, GitHub's signing key expired
on chain, the relay killed between a send and its confirmation, the RPC endpoint erroring with stale blockhashes, the
evidence missing, devnet reset), held to the page by
`test_each_dependency_failure_is_drilled_and_says_what_broke_what_is_seen_how_it_recovers_and_how_long_it_took` in
`tests/test_drills.py`; and the relay's own behaviour when its dependencies fail, in `tests/test_relay_failures.py`:
`test_a_send_that_fails_for_the_clusters_reasons_is_tried_again_on_fixed_times_and_never_given_up_while_the_token_is_good`,
`test_a_token_posted_in_a_gap_between_two_runs_is_carried_once_by_the_first_pass_of_the_next`,
`test_when_github_says_slow_down_nothing_is_asked_until_the_time_it_named_and_no_verdict_is_lost` and
`test_a_token_past_its_hour_ends_with_the_reason_and_a_refusal_is_final_at_once`.

What those tests do not show: that an outage ends, that somebody runs a relay, or that a token is carried before
its hour is over. When it is not, the token is spent time and the payment needs a new one (`/knos settle` signs a
fresh token when GitHub is back); if nobody asks, nothing pays. An outage of GitHub or of the cluster that outlasts an
order's deadline means the accepted work is not paid by this order at all.

**What is guaranteed in place of liveness: a refund path always exists.** Invariant 6: after its deadline an unpaid
order's whole balance goes back where it came from on an instruction that needs no token, no GitHub, no relay of
Knos's and no signature of the funder's, sent by anyone
(`test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` in `tests/test_order_chain.py`). The path
exists; it is not instant and not unconditional. It needs the cluster to be producing blocks and one reachable RPC
endpoint, and invariant 6 lists what can still stop it (the mint's issuer freezing the account, an upgrade that
removed the instruction). So the money of a payment that never happens is not lost and not stuck behind Knos; the
payee, whose work was accepted, is the one who bears a liveness failure.

## Not yet tested, in one list

Every row above names a test. What those tests leave out, said once more in one place:

- Invariant 4: a deployment whose verifier is another program (the test's two program ids share one verifier).
- Invariant 5: orderings of four and more moves are sampled by the machine and the random walks, not enumerated.
- Invariant 6: `RefundOrder` on the deployed bytes, in a drill.
- Invariant 7: two relayers racing against a running validator.
- The machine: standing orders, kill fees, assigned payments, a second relayer and a second mint.
