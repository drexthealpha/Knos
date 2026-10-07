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
  the ones about shares, payments and conservation; the fee-bounds harness timed out and is not proved there
  (invariant 8 says what is proved of the fee's bounds, rate by rate, by the harnesses of
  [`fee_proofs`](../programs-v2/fee_proofs/src/lib.rs)).
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
  `now > deadline` (OPEN) or `now > hold_until` (HELD). An order funded with the presentation grace (below, "A token
  shown after a deadline it was issued before") moves both by the same 7,200 seconds: `PayOrder` until
  `deadline + 7200` on a token issued by the deadline, `RefundOrder` after `deadline + 7200`, so the two stay
  disjoint. `Revert` runs only inside the warranty, `Release` only after
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

### 8. Fees never exceed the schedule

The fee is one pure function of the amount: 0.30% of it rounded down, at least 0.05. One rate, no tiers, no cap. An
order's funder pays it on top (`order_fee`), and nothing else is ever taken from an order; a job's is taken out of
its amount and is never more than it (`fee_of`). 5.00 pays 0.05; 100.00 pays 0.30; 1,000.00 pays 3.00; 5,000.00 pays
15.00; 100,000.00, the most an order holds on devnet, pays 300.00.

- **Enforced by:** `FundOrderWallet` and `FundOrderBalance` take `amount + order_fee(amount)` and store the rate and
  the fee in the order; `TopUp` takes the fee of the new amount less the fee already there; a Plan (`SetPlan`, signed
  by `FEE_OWNER`) can only lower the rate, to between 0.10% and 0.30%, until an expiry; the relayer's tip (0.05, or
  0.30 on a payee's first payment, never more than the fee) comes out of the fee, not on top of it; a refund returns
  the fee with the amount.
- **The minimum is a floor, so on a small order the fee is more than 0.30% of the amount:** 0.05 on an order of 5 is
  1%. The schedule, not a percentage, is the bound.
- **An order keeps the fee it was funded with.** The fee and its rate are in the order's account. An order funded
  under the build before this one (2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40) pays, refunds
  and reverts with that fee; a top-up of it is charged at 0.30% and never less than the fee already there. A Plan set
  under that build (0.5% to 2.5%) is read as 0.30%: no rate is above the standard one.
- **Volume rates are not on chain.** The price book's lower rates above 1M and 10M a month are a rebate by contract.
  The program knows 0.30%, the floor, and a Plan's rate for one repository owner.
- **Checked by:** the unit tests of `order_fee` and `fee_of` in [`lib.rs`](../programs-v2/knos_pay/src/lib.rs) and
  the Kani harnesses in [`proofs.rs`](../programs-v2/knos_pay/src/proofs.rs) (run by `cargo test` and `cargo kani`,
  not by pytest); `the_fee_is_thirty_basis_points_with_a_floor_of_five_cents_at_every_size`,
  `a_plan_lowers_the_rate_to_no_less_than_ten_basis_points` and `a_job_pays_the_same_rate_out_of_its_amount` in
  [`programs-v2/handlers/tests/knos_pay.rs`](../programs-v2/handlers/tests/knos_pay.rs), against the built program;
  `test_a_wallet_funds_an_order_for_any_issue_and_pays_the_fee_on_top`,
  `test_only_the_fee_owner_sets_a_plan_and_only_to_lower_the_rate`,
  `test_the_orders_repository_pays_one_payee_in_full_and_the_fee_is_split` and
  `test_top_up_adds_to_the_amount_and_the_fee_from_where_the_money_came` in `tests/test_order_chain.py`.
- **The fee's bounds, by rate** (for a mint of 6 decimals, every amount from 0 to 100,000.00 and every rate a Plan
  can set, 10 to 30 basis points). The harnesses of
  [`programs-v2/fee_proofs`](../programs-v2/fee_proofs/src/lib.rs) are about the program's own lines, copied as text
  by its `build.rs`; each ran alone within 150 seconds and [`kani.json`](kani.json) (`fee_proofs`, written by
  `scripts/kani_fee_record.py`) records them:
  - at the rates 10 to 29: at least 0.05; 0.05 or at most 0.30% of the amount; amount plus fee fits a u64:
    **verified** (two harnesses that take the rates one by one);
  - at the rate 30, the rate of an order with no Plan: at least 0.05; 0.05 or at most 0.31% of the amount; amount
    plus fee fits a u64: **verified**;
  - at the rate 30, "0.05 or at most 0.30% of the amount" is **not verified**: at that rate the fee is exactly 0.30%
    rounded down, with nothing to spare, and the solver did not answer in any of four forms. It is tested instead at
    all 10,000 remainders of an amount by ten thousand on 2,001 values of its ten-thousands, with 10,000,000 amounts
    and rates from a fixed seed and every amount within 20,000 units of each edge of the schedule at every rate,
    against a reference in 128-bit integers (`cargo test --release` in `programs-v2/fee_proofs`, not run by pytest);
  - a job's fee, at every u64 amount: never more than the amount: **verified**.

  So the statement over every amount an order may hold is **verified but for one bound at one rate**. The one
  harness over every u64 amount and every rate at once,
  `an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount` in `proofs.rs`, is recorded at the top of
  [`kani.json`](kani.json) with what it got.
- **The meter:** the fee of a month is the count beyond the free allowance times the rate, taken from prepaid
  Credits, and a batch that Credits cannot pay is refused whole
  (`test_the_first_ten_thousand_evaluations_of_a_month_are_free_and_credits_never_go_below_zero` in
  `tests/test_meter_chain.py`; `tests/test_meter_batch.py`).
- **A top-up:** `test_a_top_up_pays_the_difference_between_the_two_schedule_values_at_every_size` (across the floor,
  and to the most an order holds) and `test_a_top_up_of_a_balances_order_keeps_the_plans_rate` in
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
order's deadline means the accepted work is not paid by this order at all, unless the order was funded with the
presentation grace and the token was signed in time:

**A token shown after a deadline it was issued before (the presentation grace).** As the program was built before,
`PayOrder` compared the deadline with the chain's clock at the moment the token was SHOWN. A token the forge signed
before the deadline was refused when a relay that was down, or a congested cluster, showed it a second after. An
order can now be funded with the grace (one byte of its options, the funder's choice, fixed at funding):

- a pay token whose `iat` is at or before the deadline is accepted until `deadline + 7200` seconds;
- `RefundOrder` is refused until `deadline + 7200` and accepted from the second after, so a payment and a refund
  are never both possible in the same second, and a buyer's refund is later by at most two hours;
- a token issued after the deadline is refused as before, and so is one shown after the window.

Why 7,200 seconds and not a day: it is the longest any token issued by the deadline can live. The program takes no
token whose expiry is more than an hour after its `iat`, and the verifier refuses every token an hour after its
expiry. A longer window would delay the refund for nothing, because no token would be accepted in the extra time; a
shorter one would refuse tokens that are still good. A token GitHub itself signs lives five minutes, so in practice
it must be shown within 65 minutes of being signed. An outage longer than that still loses the payment: carrying a
proof across it would need the verifier to accept an older token, and the verifier is not changed by this build.

What the grace does not cover, and why. It is off unless the funder asks for it, so that the relay and every test
that sends a refund the second after a deadline keep their meaning for every other order; an order funded under
the build before this one never has it. A challenge of a holdback (`Revert`) is still compared with the clock when
it is shown: a challenge signed in the last minute of a warranty and shown after it is refused. A 0.3.12 bounty has
no grace. Checked by `a_token_issued_before_the_deadline_pays_after_it_and_no_refund_is_taken_meanwhile` and
`the_grace_ends_when_no_token_issued_by_the_deadline_can_live_and_the_refund_follows_at_once` in
[`adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs) (a second after the deadline; the last second a
token lives; the end of the window; the second after it; both instructions in one transaction, in both orders) and
by the unit test of `Order::in_time` in [`order.rs`](../programs-v2/knos_pay/src/order.rs), which asserts for every
boundary that a refund and a payment are never both in time.

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

## What an opponent would try, replayed against the built programs

[`programs-v2/handlers/tests/adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs) replays, in LiteSVM
against the test builds in `tests/fixtures`, the transactions `scripts/adversarial_vectors.py` records
(`cargo test --release --test adversarial` in `programs-v2/handlers`; not run by pytest): an order's address funded
again after a payment and after a refund (invariants 2, 3); the second before, at and after a deadline, the end of a
hold and the end of a warranty (5, 6); a payment and a refund, a settlement and a refund, a release and a challenge
in one transaction in both orders and in two (5); one token twice in one transaction, in two, and a meter's token
shown to `PayOrder` and a payment's to the meter (3, 4); one judge alone under a quorum of 2 and of 3; one account
and one owner behind two judges; a marker of the order that was at an address before; a token shown after a deadline
it was issued before; and orders and markers in accounts as the build before this one wrote them.

None of its tests is ignored. Two were, while the program did what they said it should not; this build fixes both,
and they run with the rest.

### A quorum counts owners of repositories, not repositories

An order with a quorum of 2 or 3 pays when that many distinct judges have passed the same artifact: the order's own
repository, a neutral run, the judge repository. The finding
(`finding_one_account_that_starts_both_runs_is_one_judge_not_two`): on a wallet's order, the account that started
the run in the order's repository could start the neutral run in another repository it owned, and the order paid.
The rule now, the same for an order funded by a wallet, by a passkey, by a comment on a forge or from a Balance
(`order_terms::distinct`; each judge's marker records the `repository_owner_id` and the `actor_id` of its run):

1. Judges whose runs were in repositories of one owner are one judge.
2. A neutral run counts only when its owner is not the owner of the order's repository and the account that
   started it is not the account that started the run in the order's repository. A wallet names a repository and
   no owner, so on a wallet's order a neutral run counts only once the order's own repository has passed the same
   artifact; before that its token is recorded and nothing is paid.

**What this enforces:** that the judges counted are different forge accounts and different owners of repositories,
as the forge signed them. **What it cannot:** that two accounts are two people. One person with two accounts, an
owner and a friend, or two parties who agreed, are two judges here; a forge signs account ids and nothing about who
is behind them. The receipt's `same_controller` field ([RECEIPT.md](RECEIPT.md)) is still what a buyer reads for
that. Two costs of the rule: a judge repository that belongs to the owner of the order's repository no longer
counts as a second judge, and on a wallet's order a neutral run and a judge repository cannot pay without the
order's own repository.

Checked by `finding_one_account_that_starts_both_runs_is_one_judge_not_two`,
`the_same_owner_behind_two_repositories_is_refused_as_a_second_judge_and_different_owners_are_accepted`,
`a_quorum_of_three_needs_three_owners`,
`on_a_wallets_order_a_neutral_run_counts_only_once_the_orders_own_repository_has_spoken` and
`on_a_balances_order_one_account_behind_both_runs_is_one_judge` in `adversarial.rs`;
`test_one_account_or_one_owner_behind_two_judges_is_one_judge` in `tests/test_order_quorum.py`; the unit test of
`distinct` in [`order_terms.rs`](../programs-v2/knos_pay/src/order_terms.rs). An order funded through a passkey is
a wallet's order on chain (the passkey's wallet signs `FundOrderWallet`), so it takes the wallet's path; no test
funds one through the passkey program and then judges it under a quorum.

### A marker does not outlive its order

A quorum marker, a standing order's `done` marker and an assignment are accounts of their own, named by their
order's address; an address is funded again once the order there was paid or refunded. The finding
(`finding_a_marker_of_the_order_before_does_not_count_for_one_funded_again_in_the_same_second`): a marker was tied
to its order by the second of the order's funding, so an order paid and funded again within one second took the
earlier marker for its own, and one new token then paid it.

Every order now stores its **incarnation**: the slot of its funding plus one. Every marker made for it carries that
number, and counts only for the order that has it. Nothing writes or counts such a marker in the slot its order was
funded in (the instruction is refused; the next slot, 400 milliseconds later, takes it). So a marker that carries
slot S was written in a later slot, while its order was there; the address was free again only after that; whatever
is funded there next is funded in a slot after S. The same holds for `done` markers and assignments, which before
this build were tied to the second (an assignment) or to nothing (a `done` marker outlived its order until someone
closed it). Markers the build before this one wrote are shorter and are told apart by their length: a quorum marker
of that build names no run and counts for nothing until its judge signs again; its `done` marker counts for an order
of that build and for no other.

Checked by `finding_a_marker_of_the_order_before_does_not_count_for_one_funded_again_in_the_same_second` (the same
second, another slot; and a funding and a judge in one transaction, refused whole),
`an_assignment_of_the_order_before_does_not_route_the_payment_of_one_funded_again_in_the_same_second`,
`a_quorum_marker_of_2_1_counts_for_nothing_until_its_judge_signs_again` and
`a_done_marker_of_2_1_counts_for_an_order_of_2_1_and_for_no_other` in `adversarial.rs`;
`test_a_marker_does_not_outlive_its_order_even_within_one_second` in `tests/test_order_quorum.py`.

### An order funded before this build

`an_order_funded_under_2_1_is_paid_and_reverted_with_the_fee_it_was_funded_with` and
`an_order_funded_under_2_1_is_refunded_a_second_after_its_deadline` in `adversarial.rs` put orders on the chain in
accounts as the build before this one wrote them (the fee and the rate of that build, no incarnation, no grace) and
pay, revert and refund them with this build: each moves the fee it was funded with, and the refund comes the second
after the deadline. These are accounts written by the test, byte for byte in the earlier layout; no order funded by
the deployed program was replayed.
