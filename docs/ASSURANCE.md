# Assurance

No outside security firm has audited anything, and nobody outside Knos has reviewed the security of the programs. All money on the programs today is test money on Solana devnet. Before any real money: an outside review, then a deployment under different program ids.

This page is about [`programs-v2`](../programs-v2) as Knos 0.3.14 has it: `knos_oidc` verifies a signed token on chain, `knos_pay` holds and pays the money (its 2.0 bounties and its 2.1 work orders), `knos_meter` counts evaluations, and `knos_passkey` is a wallet from a passkey. What the tests run is this source. What devnet runs is 0.3.12's `knos_oidc` and `knos_pay` until the upgrade executes ([SECURITY.md](SECURITY.md), section 8). That deployment can still be changed, only through a multisig and only after a public 48-hour delay. Today every key of that multisig is the founder's. The first deployment (`programs`) is not covered here: [SECURITY.md](SECURITY.md), section 8, says how it differs. SECURITY.md also says who is trusted for what and lists every known limit. This page says which tests hold the code to which rule, how to run them, and where a reviewer should look first.

## Invariants and the tests that enforce them

A test is evidence, not proof. Read the tables with three facts in mind.

- The tests were written by the people who wrote the code.
- The chain tests run the compiled programs in LiteSVM, a simulator that runs in the test process. They load test builds (`--features testkeys`), which also trust seed-derived test keys. Where a row says "real build", the test loads `knos_oidc_v2_real.so`, which is built with no features.
- The off-chain tests replace GitHub with fakes (`tests/_hub.py`), and the suite refuses every non-loopback connection.
- The tests do not run the bytes devnet runs. `scripts/drills.py` does: see "Drills on the deployed bytes" below, and [DRILLS.md](DRILLS.md) for its last run.

A test with a case count in brackets runs once per case. A Rust test is named by its file and its module.

### The verifier (`knos_oidc`)

| Invariant | Test |
|---|---|
| A token whose claims or signature were changed after signing, that another key signed, that says `alg` `none` or `HS256`, or that names a look-alike issuer, is refused. | `tests/test_oidc2_chain.py::test_every_forgery_is_refused` (16 named forgeries, signatures at or above the modulus, signatures 0 and 1) |
| On random tokens, each also with one random bit flipped, the verifier gives the same verdict as OpenSSL (60 tokens, 120 verdicts, fixed seed). | `tests/test_oidc2_chain.py::test_the_chain_agrees_with_a_reference_rsa_library_on_random_tokens` |
| On tokens made from a fixed seed (valid ones, and 102 kinds, most of them the classic ways a verifier is fooled: wrong PKCS#1 v1.5 encodings, the cube root forgery, signatures out of range or of another length, headers naming another algorithm, claims written twice, nested, escaped or out of range, payloads that are not JSON in a value the verifier has no use for, base64 in other spellings) the built program and a reference written in the test give the same answer, and no token the program accepts has an invalid signature. The recorded run: 8,855 cases, 0 disagreements, on 2026-10-05 ([fuzz.json](fuzz.json)). The default suite runs the first 250. | `tests/test_oidc_differential.py::test_the_program_and_the_reference_give_the_same_answer_on_every_case` |
| The RSA arithmetic passes Project Wycheproof's RSASSA-PKCS1-v1_5 SHA-256 vectors. 2048-bit file: 7 valid accepted, 249 invalid refused, 1 "acceptable" refused, 2 skipped (exponent not 65537). 4096-bit file: 7, 250, 1, none skipped. | `programs-v2/knos_oidc/tests/wycheproof.rs::wycheproof_rsa_2048_sha256`, `::wycheproof_rsa_4096_sha256` (run by `cargo test`, not by pytest) |
| The same vectors through the path the chain runs: the compiled program in LiteSVM, each token written and stepped. A vector's message is not a token, so each vector's opened encoding is signed again by the test key over a token's digest, with the padding, the DigestInfo and every other byte the vector's own (the test's first lines say how, and what that does not carry over). All 517 are put to the program, in the default suite: 16 valid verified, 486 invalid and 2 acceptable refused with error 70, 13 refused for their length or range (error 65; 61 for an empty signature). The arithmetic runs under the two test moduli, not the vectors' own. | `tests/test_wycheproof_chain.py::test_wycheproof_vectors_through_the_on_chain_step_path` (2 cases), `::test_carrying_a_vector_over_keeps_its_encoding_and_changes_only_the_digest` |
| A claim is read as the signer wrote it: escaped text reads the same, and a repeated, missing or wrongly typed claim is refused. | `tests/test_oidc2_chain.py::test_escaped_claims_read_as_the_same_text`; the `iss twice`, `exp as a string` and `no exp` cases of `test_every_forgery_is_refused` |
| Only GitHub's four keys of 2 Oct 2026 are accepted without an attestation. GitLab's keys and every other key need one. | `tests/test_oidc2_chain.py::test_a_genesis_key_verifies_at_once_and_only_githubs_four_keys_are_genesis` |
| Real build: none of the test keys is trusted, and the test guardian has no power. | `tests/test_oidc2_chain.py::test_the_real_build_trusts_none_of_the_test_values` |
| An attestation admits or refreshes a key only if every condition holds: the pinned workflow file and commit, the pinned account and its two repositories, a scheduled or by-hand run, a GitHub-hosted runner, the right audience, not stale. Each is broken in turn (18 wrong claims, each tried for both). | `tests/test_oidc2_chain.py::test_every_condition_of_the_attestation_is_needed_to_register_a_key_and_to_refresh_one` |
| An attested key verifies nothing for a day, and nothing until the guardian approves it. Neither alone admits it. | `tests/test_oidc2_chain.py::test_an_attested_key_verifies_only_after_its_delay_and_the_guardians_approval` |
| A key expires 30 days after it was last attested, and a refresh never moves the expiry earlier. | `tests/test_oidc2_chain.py::test_a_key_past_its_expiry_verifies_nothing_until_github_names_it_again`, `::test_refresh_moves_the_expiry_to_thirty_days_from_now_and_never_earlier` |
| A revoked key signs nothing, for ever. The guardian can approve and revoke, and can do nothing else. | `tests/test_oidc2_chain.py::test_revoke_is_for_ever`, `::test_only_the_guardian_approves_and_revokes_and_it_can_do_nothing_else` |
| Only the payer of a token account can step or close it, a verified account is final, and a verification begun under one key cannot be finished under another. | `tests/test_oidc2_chain.py::test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent` |
| A key whose Montgomery constants are wrong is refused. | `tests/test_oidc2_chain.py::test_wrong_montgomery_constants_are_refused` |
| A key is usable only when approved or genesis, active, unexpired and not revoked. A key account never reads as a verified token. | `programs-v2/knos_oidc/src/lib.rs`: `tests::a_key_is_usable_only_when_approved_or_genesis_active_unexpired_and_not_revoked`, `tests::a_key_header_can_never_read_as_a_verified_token` |
| A key of any other RS256 issuer is admitted only on the attester's run of the pinned workflow that names the issuer's URL and the key, waits the same day and the same approval, and verifies only tokens whose `iss` is that URL (2048- and 4096-bit). | `tests/test_oidc2_chain.py::test_any_rs256_issuer_is_admitted_on_githubs_signature_and_step_checks_its_iss` |
| Anyone's run of the pinned workflow, started by hand in a repository they own, refreshes a key. It never registers one. | `tests/test_oidc2_chain.py::test_anyone_refreshes_a_key_from_a_repository_of_his_own_and_nobody_registers_one_that_way` |
| An attestation registers or refreshes a key only while the key that verified it is usable. | `tests/test_oidc2_chain.py::test_an_attestation_counts_only_while_the_key_that_verified_it_is_usable` |
| A private key is its registrant's word: every token it verifies is marked private with the registrant's address, it attests nothing, and the guardian cannot approve it into anything else. | `tests/test_oidc2_chain.py::test_a_private_key_is_its_registrants_word_and_is_marked_so_in_every_token_it_verifies` |
| No token account passes the freshness check more than 25 hours after its key stopped being usable, whatever expiry it carries. | `tests/test_oidc2_chain.py::test_no_token_outlives_its_key_by_more_than_25_hours_whatever_expiry_it_carries` |
| Claims are read at the top level only, a time is plain digits, and on 300,000 random documents every wanted claim is what `serde_json` reads. | `tests/test_oidc2_chain.py::test_claims_are_read_at_the_top_level_only_and_a_time_is_plain_digits`; `programs-v2/knos_oidc/tests/claims_random.rs::every_wanted_claim_is_what_serde_json_reads_on_300_000_random_documents`, `::a_claim_is_found_under_every_spelling_of_its_name_and_a_second_copy_cannot_hide_behind_one` |

### The payment program (`knos_pay`)

| Invariant | Test |
|---|---|
| A job pays at most once. It is closed in the instruction that pays it, so a second proof finds no job, and a proof after the deadline pays nothing. | `tests/test_pay2_chain.py::test_a_proof_pays_nothing_after_the_deadline_and_no_job_twice` |
| **Random walk.** After every step, the vault of each mint holds exactly what its open and held jobs are owed. At the end, funded equals paid plus fees plus refunded. The walk mixes funding, paying, settling, refunding, binding, withdrawing, time and deliberately bad proofs, in an SPL Token mint and in a Token-2022 mint with a permanent delegate and the other extensions the regulated stablecoins carry. Default: 600 steps. CI: 10,000 steps per deployment, as four walks of 2,500, each from its own seed. | `tests/test_pay2_chain.py::test_a_random_walk_keeps_every_vault_equal_to_its_open_jobs` |
| Only the funder's balance is debited. A fund token spends only the balance it names, and only once. Only the owner and the spenders it lists can spend it. A comment in another owner's repository spends nothing. The cap per job holds. | `tests/test_pay2_chain.py::test_a_fund_token_spends_only_the_balance_it_names`, `::test_a_fund_token_works_once`, `::test_only_the_owner_and_the_listed_spenders_spend_a_balance`, `::test_a_comment_in_another_owners_repository_cannot_spend_a_balance`, `::test_a_cap_per_job_is_enforced` |
| A funding that breaks a bound, names the wrong accounts or carries the wrong token moves nothing. | `tests/test_pay2_chain.py::test_a_comment_does_not_fund_with` (32 cases), `::test_a_wallet_does_not_fund_with` (15 cases) |
| A payment goes only to the right accounts, from the right workflow at the right commit, under the job's own terms hash. A wrong fee account, a wrong destination and another terms hash are among the cases that pay nothing, and the real proof still pays afterwards. | `tests/test_pay2_chain.py::test_a_job_is_not_paid_with` (38 cases) |
| A proof pays only jobs that pin the same workflow and terms. A stranger's job on the same issue, pinned to another workflow, is not paid. | `tests/test_pay2_chain.py::test_one_proof_pays_every_job_on_the_issue_that_pins_the_same_workflow_and_terms` |
| A held payment goes only to the wallet its GitHub user bound: not to an address inside a token, not to a wallet someone else bound, not to a relayer's choice. No other proof can take it while it is held. | `tests/test_pay2_chain.py::test_a_proof_pays_the_payees_bound_wallet_whatever_address_the_token_carries`, `::test_with_no_wallet_the_job_is_held_for_the_payee_and_paid_once_they_bind_one` |
| A held payment goes back to the funder after 180 days, and not before. | `tests/test_pay2_chain.py::test_a_held_job_returns_to_the_funder_after_180_days_and_not_before` |
| Only the owner of a GitHub account can bind a wallet to it, by hand, from that account's own `knos-claim` repository. Twenty other ways are refused. | `tests/test_pay2_chain.py::test_a_github_user_binds_a_wallet_from_their_own_knos_claim_repository`, `::test_a_wallet_is_not_bound_with` (20 cases), `::test_nobody_binds_a_wallet_for_someone_else` |
| With no proof by the deadline, the money goes back where it came from, with no token, and only to that account. | `tests/test_pay2_chain.py::test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from` |
| Unspent balance money goes back only to the wallet that opened the balance, and only that wallet changes its cap and spenders. | `tests/test_pay2_chain.py::test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance`, `::test_only_the_wallet_that_opened_a_balance_changes_its_cap_and_spenders` |
| A revoked key signs nothing that pays. From the revocation on, every instruction that takes a token refuses it, tokens verified earlier included. An expired key does the same until it is attested again. Refunds, withdrawals and settling a held payment go on. A token is taken only with the key account it names. | `tests/test_pay2_chain.py::test_a_token_is_refused_once_its_key_is_revoked`, `::test_a_token_is_refused_while_its_key_is_expired_and_works_again_once_the_key_is_refreshed`, `::test_a_token_is_taken_only_with_the_key_account_it_names` |
| The guardian can pause new funding and nothing else. Payments, refunds, withdrawals and bindings ignore a pause. | `tests/test_pay2_chain.py::test_the_guardian_pauses_new_funding_only_and_nobody_else_can` |
| No money enters a Token-2022 mint that is non-transferable, starts accounts frozen, has a transfer hook program or has a transfer fee, now or scheduled (7 cases). Money already in escrow still leaves when a mint turns bad. The mints are made with Token-2022's own instructions. | `tests/test_pay2_chain.py::test_no_money_enters_in_a_mint_that_is` (7 cases), `::test_a_mint_that_turns_bad_takes_no_new_money_and_money_in_escrow_still_leaves`, `::test_a_mint_is_a_mint_of_the_token_program_passed_and_harmless_extensions_are_accepted`; `programs-v2/knos_pay/src/token.rs`: `tests::the_extensions_that_could_block_or_tax_a_payout_are_refused_and_no_other` |
| A mint's issuer keeps its powers, and the books say so: tokens sent straight to a vault belong to no job, and tokens a permanent delegate takes out leave the job waiting, unpaid, until they are back. | `tests/test_pay2_chain.py::test_tokens_sent_to_a_vault_directly_belong_to_no_job_and_stay_there`, `::test_a_mints_issuer_keeps_its_powers_over_the_vault_and_the_job_waits` |
| The faucet exists once, and only in the devnet build. A token that names another balance mints nothing. | `tests/test_pay2_chain.py::test_the_faucet_exists_once_and_the_real_money_build_has_none`, `::test_the_faucet_mints_nothing_for_a_token_that_names_another_balance` |
| The fee is 2.5%, at least 0.05 USDC, and never more than the amount. | `programs-v2/knos_pay/src/lib.rs`: `tests::the_fee_is_two_and_a_half_percent_with_a_floor_and_never_more_than_the_amount` |

### Work orders (`knos_pay` 2.1)

The same warning applies: these run test builds in a simulator. None of these instructions had run on devnet when this page was written.

| Invariant | Test |
|---|---|
| The four fixes to 2.0 paths: limits and the fee floor are whole units of the mint; the record counts real money only in Circle's USDC; money enters only in a mint whose every extension is on the list; a Balance with a side account enforces its limits per day and in total, its repositories and its workflows commit; a pay token pays exactly one job. | `tests/test_order_chain.py::test_a_jobs_bounds_and_fee_floor_are_whole_units_of_its_mint`, `::test_the_record_counts_real_money_only_in_circles_usdc`, `::test_money_enters_only_in_a_mint_whose_every_extension_is_on_the_list`, `::test_a_balance_with_a_side_account_enforces_all_of_it`, `::test_a_pay_token_pays_exactly_one_job` |
| A wallet funds an order for any issue and pays the fee on top; a comment funds one from a Balance, once. What neither can do is listed case by case. | `::test_a_wallet_funds_an_order_for_any_issue_and_pays_the_fee_on_top`, `::test_what_a_funding_wallet_cannot_do`, `::test_a_comment_funds_an_order_from_a_balance_once`, `::test_what_a_fund_token_cannot_do` |
| A payment sends each payee the whole share, the relayer its tip and Knos the rest of the fee, for one to four payees, and every unit is paid. | `::test_the_orders_repository_pays_one_payee_in_full_and_the_fee_is_split`, `::test_up_to_four_payees_share_an_order_and_every_unit_is_paid`, `::test_what_a_pay_token_and_its_relayer_cannot_do` |
| An order is held for a payee with no wallet and settled when he binds one; it goes back to its funder after the deadline and not before; tokens sent to its account cannot stop it from closing. | `::test_an_order_is_held_for_one_payee_without_a_wallet_and_settled_when_he_binds_one`, `::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before`, `::test_tokens_sent_to_an_orders_account_cannot_stop_it_from_closing` |
| Only `FEE_OWNER` sets a Plan, and only to lower the rate. A top-up adds amount and fee from where the money came. | `::test_only_the_fee_owner_sets_a_plan_and_only_to_lower_the_rate`, `::test_top_up_adds_to_the_amount_and_the_fee_from_where_the_money_came` |
| **Random walks.** After every step each order's account holds exactly what the order is owed, over funding, paying, holding, settling, refunding and topping up; and again over holdbacks, standing orders, reservations, cancellations and assignments. | `::test_a_random_walk_conserves_every_orders_money`; `tests/test_order_terms.py::test_a_random_walk_over_every_promise_conserves_every_orders_money` |
| **The judges.** A seller pays himself after the buyer's repository deleted its workflow; what a neutral run cannot do; a judge repository; the arbiter's ruling and what it cannot do; the arbiter is neither the funder nor a payee. | `tests/test_order_judges.py::test_a_seller_pays_himself_after_the_buyers_repository_deleted_its_workflow`, `::test_what_a_neutral_run_cannot_do`, `::test_the_owner_of_the_orders_repository_may_be_the_neutral_attestor`, `::test_a_public_order_that_names_a_judge_repository_is_paid_from_it_too`, `::test_the_arbiter_an_order_named_rules_who_is_paid`, `::test_what_a_ruling_cannot_do`, `::test_the_arbiter_is_neither_the_funder_nor_a_payee` |
| A private order stores no repository, no issue and only a hash of its terms, and nothing of the repository is in its account, its tokens or its logs. | `tests/test_order_chain.py::test_a_private_order_stores_no_repository_no_issue_and_a_hash_of_its_terms`; `tests/test_order_judges.py::test_a_balance_funds_a_private_order_from_its_judge_repository_and_nothing_of_the_repository_is_public`, `::test_what_the_funding_of_a_private_order_cannot_do` |
| A token under a key that is not GitHub's pays only a private order of the Balance its registrant opened. | `tests/test_order_judges.py::test_a_private_order_of_a_balance_is_paid_under_the_key_its_authority_registered`, `::test_what_a_token_under_a_key_that_is_not_githubs_cannot_do` |
| An organisation's wallet is bound only from its own `knos-claim`, by a member, by hand, and never over a binding a person made. | `tests/test_order_judges.py::test_a_pull_request_by_a_bot_is_paid_to_its_organisations_wallet`, `::test_what_an_organisations_bind_token_cannot_do`, `::test_a_collaborator_cannot_rebind_a_person_who_bound_his_own_wallet` |
| A holdback stays through the warranty and then goes to the wallets it recorded; a revert inside the warranty returns it and its fee to the funder. | `tests/test_order_terms.py::test_a_holdback_stays_in_the_order_through_the_warranty_and_then_goes_to_the_wallets_it_recorded`, `::test_a_revert_inside_the_warranty_returns_the_holdback_and_its_fee_to_the_funder`, `::test_an_order_with_a_holdback_is_never_held_and_a_standing_one_cannot_have_a_holdback` |
| A standing order pays its rate once per pull request. A reservation, a cancellation with notice and the kill fee. An assignment, which only the assignee can change. A used marker closes only once no token it stands for can be accepted. | `tests/test_order_terms.py::test_a_standing_order_pays_its_rate_once_per_pull_request_until_less_than_one_rate_is_left`, `::test_a_reservation_a_cancellation_with_notice_and_the_kill_fee`, `::test_a_payee_assigns_an_orders_payment_and_only_the_assignee_can_change_it`, `::test_a_used_marker_is_closed_once_no_token_it_stands_for_can_be_accepted` |

### The meter (`knos_meter`) and the passkey wallet (`knos_passkey`)

| Invariant | Test |
|---|---|
| An evaluation is billed and counted once, a retry is free, and a rejection is billed. The first 10,000 of a month are free and credits never go below zero. | `tests/test_meter_chain.py::test_an_evaluation_is_billed_and_counted_once_and_a_retry_is_free`, `::test_a_rejection_is_billed`, `::test_the_first_ten_thousand_evaluations_of_a_month_are_free_and_credits_never_go_below_zero` |
| Only the run the Credits account pins, in the buyer's own repository, on a first attempt, counts. A revoked key, an expired key and a private key count nothing. | `::test_another_workflow_another_owner_or_a_second_attempt_is_refused`, `::test_a_revoked_key_counts_nothing`, `::test_an_expired_key_a_private_key_and_another_account_in_the_keys_place_count_nothing` |
| The fee goes to `FEE_OWNER` and nowhere else; only the wallet that opened the credits withdraws them, and only to itself; only `FEE_OWNER` sets a Plan. The counters equal the logs. | `::test_the_fee_goes_to_the_fee_owner_and_nowhere_else`, `::test_only_the_authority_withdraws_and_only_to_itself`, `::test_a_plan_sets_the_rate_until_it_expires_and_only_the_fee_owner_sets_one`, `::test_the_counters_equal_the_logs` |
| A relayer gets a marker's rent back once no token of its month can be recorded, and nobody else does. | `::test_the_relayer_gets_a_marks_rent_back_once_no_token_of_its_month_can_be_recorded`, `::test_what_a_relayer_pays_for_evaluations_and_gets_back` |
| A passkey's withdrawal moves exactly what was signed, once, in order: a wrong nonce, another passkey's signature, a changed amount, destination or mint, a missing or misplaced precompile instruction, one that checks bytes elsewhere, and a high-s signature are refused. | `tests/test_passkey_chain.py::test_withdrawals_follow_one_another_and_none_can_be_sent_twice`, `::test_a_wrong_nonce_is_refused`, `::test_another_passkeys_signature_is_refused`, `::test_a_changed_amount_destination_or_mint_is_refused`, `::test_a_missing_or_misplaced_precompile_instruction_is_refused`, `::test_a_precompile_instruction_that_checks_bytes_elsewhere_is_refused`, `::test_a_high_s_signature_is_refused_and_the_client_lowers_it`, `::test_what_webauthn_requires_of_the_assertion` |
| The precompile itself runs in the simulator the tests use; a wallet is paid before it exists. | `tests/test_passkey_chain.py::test_the_precompile_itself_runs_here`, `::test_a_wallet_is_paid_before_it_exists_and_one_transaction_opens_it_and_withdraws` |

### The off-chain flow

This is the code that decides, before anything is signed, whether a merge earns a payment and who gets it. The chain does not check these decisions.

| Invariant | Test |
|---|---|
| **Random terms.** Equal terms are the same bytes, and a hash names one set of terms. Of 300 random terms, each with 12 damaged copies (seed 600), every copy is either refused or is exactly the bytes of the terms it reads as. | `tests/test_terms.py::test_equal_terms_are_the_same_bytes_and_the_hash_is_their_sha256`, `::test_no_bytes_but_the_canonical_ones_are_ever_read` |
| A required check is in exactly one of six states. Only every check passed, with every changed file in scope, is acceptance. Each state has its own outcome in the reply. | `tests/test_terms.py::test_a_required_check_is_in_exactly_one_of_six_states`, `::test_only_every_check_passed_and_nothing_out_of_scope_is_acceptance`; `tests/test_flow.py::test_each_state_of_a_required_check_has_its_own_outcome` (6 cases) |
| A check of the same name from another app is not the check. Knos's own jobs are never evidence. A description cannot change what is required. | `tests/test_terms.py::test_only_the_app_the_terms_name_can_produce_the_check`, `::test_knos_own_jobs_are_never_evidence`, `::test_a_description_cannot_change_what_is_required` |
| A person's pull request pays that person, whatever it says. A bot's pays nobody until GitHub authenticates a person. | `tests/test_who.py::test_a_persons_pull_request_pays_that_person_whatever_it_says`, `::test_a_bots_pull_request_pays_nobody_until_github_authenticates_a_person`, `::test_the_three_ways_are_tried_in_order` |
| Prose never decides. A description is a hint. An edited comment does not count. A maintainer is whoever GitHub says can write now. | `tests/test_who.py::test_a_description_is_a_hint_to_show_and_never_decides`, `::test_a_comment_counts_only_as_it_was_first_written`, `::test_a_maintainer_is_whoever_github_says_can_write_now` |
| An assigned issue pays only its assignee's pull request. A maintainer's `/knos reject` before the merge means nobody is paid. | `tests/test_who.py::test_an_assigned_issue_pays_only_its_assignees_pull_request`, `::test_a_maintainers_reject_before_the_merge_means_nobody_is_paid`; `tests/test_flow.py::test_a_pull_request_a_maintainer_rejected_before_the_merge_is_not_paid` |
| Nothing is decided on half an answer. Where GitHub did not answer, nobody is paid until `/knos settle` runs again. | `tests/test_who.py::test_at_the_merge_what_github_did_not_answer_pays_nobody_yet`, `::test_at_the_merge_a_bots_pull_request_is_not_decided_on_half_an_answer` |
| The pull request must close the issue. A description edited after the merge closes nothing. A pull request merged before the bounty was funded does not take it. | `tests/test_closing.py::test_githubs_documented_keywords_close_an_issue`, `::test_what_is_not_a_closing_keyword_closes_nothing`, `::test_a_description_edited_at_or_after_the_merge_is_told_from_one_edited_before_it`; `tests/test_who.py::test_at_the_merge_the_pull_request_must_close_the_issue_it_is_paid_for`, `::test_a_description_edited_after_the_merge_closes_nothing_where_money_moves`; `tests/test_flow.py::test_a_pull_request_merged_before_the_bounty_was_funded_does_not_take_it`, `::test_a_description_edited_after_the_merge_takes_no_bounty` |
| Where the money goes: the bound wallet, else the payee's own unedited address comment, else it is held. | `tests/test_who.py::test_the_payout_address_is_the_bound_wallet_else_the_payees_own_unedited_comment`; `tests/test_flow.py::test_where_the_money_goes_a_bound_wallet_else_the_authors_address_else_it_is_held` |
| The gate holds a bounty's pull request to the terms and to who is paid. A claim on a commit with no check runs is refused. | `tests/test_gate.py::test_the_gate_holds_a_bountys_pull_request_to_the_terms_and_to_who_is_paid`, `::test_a_claim_on_a_commit_with_no_check_runs_is_refused_at_the_merge` |
| Only a person GitHub says can write funds from a comment, and a balance in a made-up token is never spent by a comment. | `tests/test_flow.py::test_only_someone_with_write_access_may_fund`, `::test_a_strangers_balance_in_a_token_of_their_own_is_never_spent_by_a_comment` |
| Only what a push to the default branch merged is settled. In tests mode, the job after the judge signs nothing it has not read again itself. | `tests/test_flow.py::test_only_what_a_push_to_the_default_branch_merged_is_settled`, `::test_the_job_after_the_judge_signs_nothing_it_has_not_read_again_itself` |
| A relayer refuses what the chain would refuse before it spends a fee, and a token carried twice or by two relayers is done once. | `tests/test_relay2.py::test_a_fund_token_costs_nothing_with` (27 cases), `::test_a_proof_costs_nothing_with` (13), `::test_a_claim_costs_nothing_with` (12), `::test_a_token_relayed_twice_or_by_two_relayers_is_done_once` |
| A job's terms are the ones its hash names, whatever else was logged at its address. | `tests/test_relay2.py::test_a_jobs_terms_are_the_ones_its_hash_names_whatever_else_was_logged_at_its_address` |

### The workflows

| Invariant | Test |
|---|---|
| No job that runs pull request code can mint a token. The job that runs it can only read, hands nothing on, and has no secret. The job that signs checks nothing out and runs no git. | `tests/test_workflows2.py::test_a_token_is_asked_for_only_by_jobs_that_run_no_pull_request_code_and_check_nothing_out`, `::test_the_job_that_runs_pull_request_code_can_only_read_and_hands_nothing_on` |
| No workflow is started by `pull_request_target`. | `tests/test_workflows2.py::test_every_workflow_parses_and_none_is_started_by_pull_request_target` |
| No caller can change which code judges: no inputs, one exact release of `knos`, dependencies no newer than one date. | `tests/test_workflows2.py::test_no_caller_can_change_which_code_judges`, `::test_the_release_the_workflows_install_is_this_one_and_its_cutoff_comes_after_it` |
| Every action is a full commit from the pin list, and every called workflow is a pinned commit. | `tests/test_workflows2.py::test_every_action_is_a_commit_listed_in_action_pins_and_every_called_workflow_is_a_pinned_one` |
| Permissions start empty and each job gets the least. Nothing of Knos's can write to code, releases or settings. | `tests/test_workflows2.py::test_permissions_start_empty_and_each_job_gets_the_least` |
| Text a person wrote never reaches a shell except through the event file or an environment variable. | `tests/test_workflows2.py::test_untrusted_text_reaches_a_shell_only_through_the_event_file_or_env` |
| The only secret is the optional relay key, and only a step that can mint gets it. | `tests/test_workflows2.py::test_the_only_secret_is_the_optional_relay_key_and_only_a_step_that_can_mint_gets_it` |
| No job of the payment flow restores or saves a cache, and no job that signs or sees a secret uses one. | `tests/test_workflows2.py::test_no_job_of_the_payment_flow_restores_or_saves_a_cache`, `::test_no_job_that_signs_or_sees_a_secret_uses_a_cache` |
| A wallet is bound by hand only: the claim file names the pinned commit and takes the address from the one input. | `tests/test_workflows2.py::test_the_claim_caller_names_the_pinned_commit_and_takes_the_address_from_the_right_place` |
| The called workflows refuse, by their own conditions, an edited comment and a push that is not to the default branch. | `tests/test_workflows2.py::test_the_called_workflows_refuse_by_themselves_what_no_caller_should_send` |

## How much a verdict can carry

A bounty in tests mode is paid on a judge's verdict, and there are three ways the judge can run the pull request's code. Every verdict says which one it was (`assurance` in the verdict's JSON, with one sentence, `assurance_means`), and so do the terms when they are shown to the funder. The counts are from [TAMPER.md](TAMPER.md): 63 cheating pull requests, written by the people who wrote the judge. They are counts for that suite. They are not a proof: the claim is "0 of 63 in this suite", never "cannot be cheated".

| `assurance` | How the pull request's code runs | Measured | What it does not stop |
|---|---|---|---|
| `in-process` | The acceptance tests import it: it shares a process with the test runner (the python, node, go, rust, ruby and command runners). On a machine with the sandbox, as another user with no network. | 7 of 63 attacks in this suite were accepted. | Code written to forge the runner's report from inside, and code that answers the fixed examples. On the second deployment a bounty is never paid on this mode alone: it waits for a maintainer's merge. |
| `black-box` | As a separate process on the judge's machine; the check never loads it and compares only what it prints (`$KNOS_RUN`). On a machine with the sandbox, as another user with an empty environment and no network. | 0 of 63 in this suite were accepted. | What the machine leaves open to any of its users: writing to shared directories, using all of its memory and processes ([TAMPER.md](TAMPER.md), "Escapes": measured). Two machines can differ, so a rerun elsewhere is the same judge and not the same environment. |
| `hermetic` | Black-box, with `image` in the terms: each `$KNOS_RUN` call is a new container of that image, pulled by digest, with no network, a read-only root, a tmpfs work directory, uid 65534, no capabilities, no host mount but the pull request's tree (read-only) and the bundle's `public/` folder if it has one (read-only), and limits on memory, CPUs, processes and time. The check, its reference answers and the judge stay outside. | 0 of 63 in this suite were accepted by the black-box check it runs. The container itself has not been measured on the machine that wrote TAMPER.md: its five escape probes are listed there as "not run here". | A fault in the container runtime or the kernel. A registry that stops serving the digest: then nobody can run the judge again. A check that is wrong: the image fixes where the code runs, not what the buyer wrote. |

What `hermetic` adds beyond isolation is that the judgment can be repeated. The image's digest is in the terms, so it is in the terms hash that is funded. The verdict records the digest the runtime reported after the pull, the runtime and its version, the limits, and a hash of each of the two trees. `knos judge rerun <verdict file or bundle folder> --base DIR --pr DIR` checks that the trees are the ones judged, runs the same judge in the same image and prints `agree` or `disagree` (exit 0 or 1). A local image under that name with another digest stops the judge before any of the pull request's code runs. A check that draws its inputs at random draws new ones on a rerun: the verdict is expected to be the same, the inputs are not.

Not done: the funding flow does not yet read `image` from `.knos/proof.toml` into the terms it funds (the field, its validation and the judge are in place; `knos.terms.build(..., image=...)` takes it), and `knos proof judge` does not print the assurance line (it is in the JSON it writes with `--evidence`). The end-to-end test in the last row below ran in a real container on GitHub's runner: the staging repository's job `hermetic judge (staging)`, run 37217535106, which fails unless that test passed and Docker started a container of the image pinned by digest (Docker 28.0.4; it started 11). No hermetic judgment has been run on devnet.

| Invariant | Test |
|---|---|
| The container's command line is exactly the documented one: no network, read-only root, tmpfs work directory, uid 65534, no capabilities, the tree and the public suite as the only mounts and both read-only, the four limits. | `tests/test_judge_hermetic.py::test_the_command_line_is_exactly_this`, `::test_the_only_host_paths_in_the_command_line_are_the_tree_and_the_public_suite_both_read_only` |
| An image is taken only as `<registry>/<name>@sha256:<64 hex>`. A tag is refused at funding, in the terms and in the command line, with what to write instead. The image is part of the terms hash. | `tests/test_terms.py::test_an_image_is_part_of_the_terms_and_of_their_hash`, `::test_a_tag_without_a_digest_is_refused_at_funding_with_what_to_write` (4 cases); `tests/test_judge_hermetic.py::test_an_image_that_is_not_pinned_by_digest_is_refused` (12 cases) |
| The judge runs the image in the terms or does not run: another digest on the machine, a failed or slow pull, no runtime, a daemon that does not answer, an in-process bundle and a setup command are each refused before pull request code runs. | `tests/test_judge_hermetic.py::test_pull_refuses_another_digest_a_failed_pull_a_slow_one_and_a_tag`, `::test_a_local_image_with_another_digest_stops_the_judge_before_any_pull_request_code_runs`, `::test_an_image_is_never_swapped_for_the_host` |
| With an image, every run of the pull request's code goes through the container command line (checked against a stand-in runtime that records it), each call is killed after its time limit, and the verdict records the digest. | `tests/test_judge_hermetic.py::test_with_an_image_the_submission_runs_only_through_the_container_and_the_verdict_records_the_digest`, `::test_the_script_runs_each_call_in_its_own_container_and_kills_it_after_the_time_limit` |
| Every verdict names its assurance, and the sentences say "of 63", never more. | `tests/test_judge_hermetic.py::test_every_verdict_names_its_assurance_and_what_it_means`; `tests/test_terms.py::test_the_terms_say_which_assurance_they_buy` |
| `knos judge rerun` agrees with an honest verdict, disagrees with a changed one, and refuses other trees. | `tests/test_judge_hermetic.py::test_rerun_judges_the_same_artifact_in_the_same_image_and_says_agree_or_disagree`, `::test_rerun_refuses_other_trees_another_image_and_a_file_that_is_no_verdict` |
| In a real container: the honest fix passes, a pull request that changes nothing does not, a rerun agrees, and the five escapes are held. Skipped where no container runtime answers, which includes the machine these documents were written on; run in a real container by the staging repository's run 37217535106. | `tests/test_judge_hermetic.py::test_end_to_end_in_a_real_container` |

## A second execution: what a neutral judge runs itself

A signed token says which workflow ran. It does not say what the workflow read. For an order paid by its black-box
acceptance suite, the neutral judge (`attest.yml`, started by hand in the attester's own repository) therefore does
not read the buyer repository's result for the suite: its first job fetches the two commits and runs the suite
again, and only the second job, which runs none of that code, can ask GitHub for the token
([SECURITY.md, section 20](SECURITY.md#20-a-neutral-judge-that-runs-the-suite-again)). No program changed for
this.

What that adds: one more execution of the same suite, under another account, on a runner the buyer does not
configure, with a verdict file that says so (`reexecuted: true`, the assurance, the image's digest, a hash of each
tree, the runner's environment). What it does not add: another suite (a suite that is wrong is wrong twice),
another GitHub (both runs are GitHub's runners and GitHub's copy of the commits), or another person (two accounts
of one person are one judge). An order paid on the merge cannot be re-executed, because its checks are the
repository's own: the neutral judge reads their results and its verdict says "this judge read the buyer
repository's check results; it did not run them".

Not done: no run of this on GitHub or on a cluster. The table is what is tested here, against stand-ins for GitHub
and the chain and, for the last row but one, the program in a simulator.

| Invariant | Test |
|---|---|
| The buyer's check results all say success and the suite fails when it is run again: the neutral run signs nothing. | `tests/test_attest_rerun.py::test_the_buyers_checks_say_success_and_the_suite_fails_when_it_is_run_again_so_nothing_is_signed` |
| The honest case is signed with the audience the program takes today, and the verdict is posted beside the token. | `tests/test_attest_rerun.py::test_the_honest_case_is_signed_on_the_run_the_attester_made_and_the_verdict_is_posted_beside_the_token` |
| The verdict is untrusted text: another order, pull request, issue, repository, base, head or bundle, a failed or in-process run, an unknown field, a wrong type and an oversized or malformed text are each refused. | `tests/test_attest_rerun.py::test_a_verdict_is_untrusted_text_held_to_this_order_this_commit_and_these_terms` |
| Terms that name an image are signed only for a run in that image, and the verdict records the digest. | `tests/test_attest_rerun.py::test_terms_that_name_an_image_are_signed_only_for_a_run_in_that_image_and_the_verdict_records_the_digest` |
| The bundle that is run is the one that was funded; a judge that cannot run is a suite that did not pass. | `tests/test_attest_rerun.py::test_the_bundle_that_is_run_is_the_one_that_was_funded_and_a_judge_that_cannot_run_is_a_suite_that_did_not_pass` |
| An order paid on the merge is not re-executed, and its verdict says the results were read and not run. | `tests/test_attest_rerun.py::test_an_order_paid_on_the_merge_has_no_suite_to_run_so_the_run_reads_the_check_results_and_says_so` |
| The real judge, run again on a sample tree, passes the fix and fails a pull request that changes nothing (not on Windows). | `tests/test_attest_rerun.py::test_the_real_judge_run_again_passes_the_fix_and_fails_a_pull_request_that_changes_nothing` |
| With `quorum 2`, the buyer's token alone pays nothing when the second run fails, and pays when it passes (the program, in a simulator). | `tests/test_attest_rerun.py::test_with_a_quorum_of_two_the_buyers_green_checks_alone_pay_nothing_when_the_second_run_fails` |
| The job that runs the suite has no `id-token` permission, no secret and one output; the job that signs checks nothing out, runs no git, takes no artifact and starts only after it. | `tests/test_workflows2.py::test_attests_first_job_runs_the_suite_again_with_no_way_to_sign_and_hands_on_one_verdict`, `::test_attest_takes_facts_never_code_reads_the_public_record_and_asks_for_one_signed_statement` |

## Three independent readers

An order can ask that more than one reader pass the same pull request at the same commit before it pays
(`quorum 2`, `quorum 3`). There are three kinds of reader, and since this release a funding comment can name all
three:

    /knos fund 20 checks: test quorum 3 judge: owner/repo

| Reader | Who it is | What makes it separate |
|---|---|---|
| a | The buyer repository's own run (`prove.yml`). | It is the buyer's. |
| b | A neutral run (`attest.yml`) that someone starts by hand in a repository they own. For an order paid by its suite it runs the suite again (the section above). | The program refuses one in the order's own repository and, for an order funded from a Balance, one started by the funder or the Balance's owner. |
| c | A run in the judge repository the comment names. | Its id is fixed at funding, in the options the fund token signs (`judge_repo_id`); the program takes reader c's word from that repository and no other. |

The name is resolved to its id through GitHub's API when the comment is answered. The program cannot see who owns a
repository, so the funding flow refuses, in words, a judge repository that is the buyer's own, or whose owner is the
buyer repository's owner, the funder, or the account the issue is assigned to: two accounts of one owner are one
judge. `judge:` without a quorum is refused too, because that repository's run alone could then have the order paid.

What this does not give: three suites (all three run or read the same one), three hosts (all three are GitHub's
runners) or proof that three owners are three people. Not checked at funding: that whoever later starts the neutral
run is not the judge repository's owner, since nobody knows at funding who that will be. Not done: no order with three
readers has been funded or paid on GitHub or on a cluster; the judge repository's run is the pinned `attest.yml` or
`prove.yml` there, and no caller workflow for a judge repository is published.

| Invariant | Test |
|---|---|
| The comment's judge repository becomes the id in the options the fund token signs; the terms bytes hash to what the token names; the program takes both. | `tests/test_flow_quorum3.py::test_a_fund_comment_names_the_third_reader_and_the_program_takes_exactly_what_it_signed` |
| The order pays only after a, b and c have each passed the same pull request; one reader twice counts once; a run in another repository is no judge (the program, in a simulator). | the same test; `tests/test_order_quorum.py::test_a_quorum_of_three_needs_the_judge_repository_too` |
| A neutral run that is the buyer's again is refused and the order is not paid; a judge repository owned by a side of the order is refused at funding, and the reply says why. | `tests/test_flow_quorum3.py::test_two_readers_of_one_owner_are_one_and_the_order_is_not_paid` |
| The reply to the funder says who the readers are and how many must agree. | `tests/test_terms.py::test_the_sentence_about_a_quorum_names_each_reader_and_how_many_must_agree` |

## Acceptance policies: versions, changes, appeals, defects

An acceptance policy is what decides "accepted" for an order: its terms (the checks, the paths, the acceptance suite's
hash, the image, the repository's `.knos/policy.yml` hash). Nothing in this section is a new mechanism; it says how
the existing ones answer four questions, and which test holds each.

**How a policy is versioned.** Its version is the sha256 of its canonical bytes. The order keeps that hash, every pay
token carries it, and the meter records it as `policy` in each evaluation's id. Change a threshold, a gold label, a
check or a path and the hash is another one. There are no version numbers to forget to bump.
`knos terms diff <a> <b>` (each a template's name or a file that holds terms) prints one plain sentence for each
difference between two versions, for whoever has to approve the change.

**Who may change it.** Before funding: whoever can write to the repository's default branch, since the suite and the
policy file are read from there, and whoever funds, since the comment names the checks. After funding: nobody. The
order holds the hash; a payment under other terms is refused by the program; a pull request that edits `.knos/**` or
`.github/**` is out of scope by the terms' own `deny`. A buyer who wants other terms lets the order run out or
cancels it with seven days' notice, and funds a new one. A supplier who thinks the suite is wrong does not get it
edited under an open order: that is the next question.

**How a supplier appeals.** Three routes, each fixed when the order was funded:

1. The neutral run. For an order that allows it (the default), the supplier starts `attest.yml` in a repository of
   their own, and for an order paid by its suite that run executes the suite again. A buyer who deletes the workflow,
   or whose run said no for a reason that is not in the terms, does not decide alone.
2. The arbiter. If the funder named one (`arbiter @login`), that person's ruling pays whom it names, without a pull
   request and without waiting for a quorum. The arbiter is neither the funder nor a payee. With no arbiter named
   there is nobody to rule: the reply to the funding comment says "No arbiter is named".
3. The challenge window, which runs the other way: inside the warranty anyone can run the pinned judge again on the
   commit that was paid, and a run that fails returns what the order still holds to the funder.

What an appeal cannot do: change the suite. A suite that is wrong is wrong for every reader; only the arbiter's
ruling pays against it.

**A defect found after acceptance.** If the order has a warranty (`warranty N`, with `holdback N` percent), that
share of the payment stays in the order for N days. A revert token from one of the order's judges inside that time
sends it back to the funder; after it, the share is released to the payee and no challenge is heard. With no
holdback, a payment is final when it is made, and the reply to the funding comment says so. The meter has no
reversal either: an accepted evaluation stays accepted, and a later defect is a correction line in the ledger
([METER.md](METER.md)), not a changed count.

| Invariant | Test |
|---|---|
| Equal terms give equal bytes and one hash; anything else is another version. | `tests/test_terms.py` (the canonical form, from its first test) |
| `knos terms diff` names each difference between two versions in a plain sentence, and says so when there is none. | `tests/test_terms.py::test_terms_diff_says_in_plain_words_what_changed_between_two_versions_of_a_policy` |
| The repository's policy file is hashed into the terms of an order funded under it. | `tests/test_flow_orders.py::test_the_repositorys_policy_decides_who_may_fund_how_much_and_what_an_order_asks_when_its_funder_does_not_say` |
| The arbiter an order named rules who is paid; a ruling cannot do more than that. | `tests/test_order_judges.py::test_the_arbiter_an_order_named_rules_who_is_paid`, `::test_what_a_ruling_cannot_do` |
| A stranger's failing neutral run inside the window stops the release, and after it does not. | `tests/test_order_auto.py::test_a_strangers_neutral_failing_run_inside_the_window_stops_the_release_and_after_it_does_not` |
| A holdback stays through the warranty; a revert inside it returns the holdback and its fee to the funder; judges a, b and c sign a revert and nobody else. | `tests/test_order_terms.py::test_a_holdback_stays_in_the_order_through_the_warranty_and_then_goes_to_the_wallets_it_recorded`, `::test_a_revert_inside_the_warranty_returns_the_holdback_and_its_fee_to_the_funder`, `::test_judges_a_b_and_c_sign_a_revert_and_nobody_else` |

## Drills on the deployed bytes

The tests above load builds made for testing. Three scripts go further, and each says what it could not do.

**`scripts/drills.py`** reads `knos_oidc` and `knos_pay` from devnet (their ProgramData accounts, through `getAccountInfo`), prints the sha256 of each with its trailing zeros trimmed, loads exactly those bytes into LiteSVM at their real ids, and runs the safety paths with a clock it moves. Its table is [DRILLS.md](DRILLS.md). What that gives:

- Run on the deployed bytes with real signatures by keys the script makes, since anyone may send these instructions: a wallet's job is refunded only after its deadline, and only to its funder; a key expires 30 days after it was registered and the verifier's first step refuses it from that second on; only GitHub's four keys of 2 Oct 2026 are taken without an attestation.
- Run on the deployed bytes with the guardian's signature simulated: the guardian's pause refuses new funding and ends by itself after 7 days; nobody but the guardian revokes a key, and a revoked key verifies nothing. The guardian is the vault of a Squads multisig and has no private key. The script turns the simulator's signature check off for that one transaction and names the vault as a signer. So these rows show what the programs do once the guardian has signed, and that no other signer passes. They do not show the multisig's vote.
- Run on the deployed bytes with one account written by hand: a held payment goes back to the funder after 180 days and not before. A job is held only after a GitHub-signed proof, so the script funds a job through the program and then writes the three fields `Pay` writes when it holds one. The refusals and the refund are the deployed program's.
- Not run until the release run gives it real tokens (`--tokens FILE`): a key refreshed by the rotate workflow's token, a bounty funded and paid, the same tokens refused a second time, and a token refused once the guardian has revoked its key. The deployed build trusts GitHub's keys only, so no token made here would be accepted. `tests/test_drills.py` runs these four with tokens the test key signed, against the test builds served by a fake RPC: that tests the script, not the deployed bytes.

No row is a transaction on devnet. The simulator is LiteSVM in the version the tests use; a difference between it and a validator would not show here.

**`scripts/drill_upgrade.sh`** runs the upgrade path against a validator on the machine that runs it, with the real Squads program: a no-op upgrade is proposed and approved, its execution is refused before 48 hours by the Squads program itself (`TimeLockNotReleased`), the validator's clock is moved, the upgrade is executed, and a second proposal is cancelled and can never run (`InvalidProposalStatus`). With `--from-devnet` it needs no key: it copies the deployed bytes of both programs, the Squads program and both multisig accounts from devnet into a validator of its own, and replaces each member's key in the two multisig accounts with a key made for the drill. Threshold and time lock are devnet's. What that leaves out is the members' real keys, by design. Against `scripts/deploy_v2.sh --localnet --keep` it uses the key folder's member keys instead.

**`scripts/replay_tokens.py`** keeps real tokens and verifies them again. `--capture OWNER/REPO` reads a public repository's token comments into a JSON Lines file, each token with the issuer's key set of that day, and keeps only tokens a key of that set signed. `--corpus FILE` loads the verifier's deployed bytes into LiteSVM, sets the clock to each token's `iat`, has the token written and stepped by the relay code the public worker runs, and prints how many verified, by repository and by key. `tests/test_replay_tokens.py` does both with tokens the test key signed. The file of real tokens is made by the release run; none is committed here, and no real token has been replayed by these tests.

## What was read as an attacker

Both programs were read line by line against the attacks below before this release. This is the author's own review, not an outside audit.

In this part `T` is `tests/test_oidc2_chain.py`.

### The verifier: reviewed and found sound

RSA

- Signature equal to or above the modulus: refused before any arithmetic (`rsa::geq`, error 65). `T::test_every_forgery_is_refused`
- Signature shorter or longer than the modulus, padded base64, a 2048-bit signature under a 4096-bit key and the reverse: the decoded length must be exactly `4 * limbs` (65). `T::test_every_forgery_is_refused`
- Signature 0 or 1: the result is not the encoding (70). `T::test_every_forgery_is_refused`
- Lenient PKCS#1 v1.5 parsing (short padding, wrong DigestInfo, missing NULL, bytes after the digest): `pkcs1_sha256_ok` compares every byte of `00 01 FF.. 00 DigestInfo digest` over the whole modulus length, so there is nothing to parse. `programs-v2/knos_oidc/tests/wycheproof.rs::wycheproof_rsa_2048_sha256`, `::wycheproof_rsa_4096_sha256`; `T::test_the_chain_agrees_with_a_reference_rsa_library_on_random_tokens`
- Another exponent: none is stored or sent; Step always does 16 squarings and one multiplication (65537). A key registered with another exponent only fails to verify. Same Wycheproof tests.
- A key used before its Montgomery constants are checked: `load_key` needs state 1 (68); KeyParams checks `n0inv * n[0] == -1` and `r2 == R^2 mod n` on chain and runs once (66, 69). `T::test_wrong_montgomery_constants_are_refused`, `T::test_nothing_computed_for_one_token_serves_another_and_no_account_stands_in_for_another`
- An even modulus, or one with its top bit clear (a short modulus padded to 256 or 512 bytes, which would give a second hash for the same key): refused at RegisterKey (66). `T::test_wrong_montgomery_constants_are_refused`
- A step plan that does not match the key: the program counts the squarings itself (`T_DONE`, never above 16), so any split gives s^65537 or runs out of compute and leaves nothing behind. `T::test_the_plans_fit_the_longest_token_the_program_takes`, `T::test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent`, `T::test_nothing_computed_for_one_token_serves_another_and_no_account_stands_in_for_another`
- The half-done power of one token used for another: Write refuses once the first Step has run (69), and closing zeroes the account. `T::test_nothing_computed_for_one_token_serves_another_and_no_account_stands_in_for_another`
- A verification begun under one key and finished under another: the key's address is stored at the first Step and compared at every later one (68); a key's modulus never changes and a key account is never closed. `T::test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent`
- Someone else's token account stepped, resumed or closed: its address is derived from the signer and the id (67). `T::test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent`
- A verified account changed afterwards: Write and Step refuse it (69). `T::test_a_token_account_belongs_to_its_payer_and_closes_with_its_rent`

Token and claims

- `alg` none or HS256, `alg` twice: refused (71, 62). `T::test_every_forgery_is_refused`, `T::test_claims_are_read_at_the_top_level_only_and_a_time_is_plain_digits`
- Another issuer's key vouching for `iss`, a look-alike `iss`, `iss` twice: `iss` must be the text of the key's own issuer, and a wanted claim written twice is refused (72, 62). `T::test_every_forgery_is_refused`, `T::test_a_gitlab_token_under_a_4096_bit_key_is_verified_in_six`
- A claim's name inside a nested object, a list or a string's text: only top-level keys are read; strings are skipped with their escapes. `T::test_claims_are_read_at_the_top_level_only_and_a_time_is_plain_digits`
- A claim RegisterKey reads written twice (first value harmless, second not, or the reverse): refused (62). Same test.
- Escaped characters to make two spellings differ: `\/ \\ \" \u00XX` (printable ASCII) are decoded before comparing, every other escape is refused (63). `T::test_escaped_claims_read_as_the_same_text`
- `exp` as text, with a sign, an exponent, a fraction, a leading zero, 19 digits, a list, an object, or twice: refused (63, 62). `T::test_claims_are_read_at_the_top_level_only_and_a_time_is_plain_digits`, `T::test_every_forgery_is_refused`
- Ids that only start like the right one, or are not numbers: `parse_u64` takes digits only and compares the whole value (74, 63). `T::test_every_condition_of_the_attestation_is_needed_to_register_a_key_and_to_refresh_one`
- Bytes after the payload object, a payload that is not an object, a fourth part: refused (61); a part that is not base64url changes the signed bytes (70), and the base64 decoder (`strict.rs` for the verifier since 2.2) refuses stray trailing bits (60, read, no test on chain). `T::test_every_forgery_is_refused`
- Very long tokens and values: at most 8,192 bytes, checked before anything is written (64); the longest and the costliest shapes still verify inside the compute limit. `T::test_the_plans_fit_the_longest_token_the_program_takes`

The attestation that registers or refreshes a key

- Another repository, another owner, an owner and a repository that do not belong together, another event, another workflow file, the same file name in another repository, another commit, a self-hosted runner, an audience naming another issuer, another key, capitals, or another action; a missing claim; a claim of the wrong type: each refused (74, 63). `T::test_every_condition_of_the_attestation_is_needed_to_register_a_key_and_to_refresh_one`
- An attestation signed by GitLab's key with the same claims: the verifying key's issuer must be GitHub (74). Same test.
- An account that is not a verified token (one still being written, a key account, a wallet, nothing): refused (73); a key account's first byte is never 2. Same test; `programs-v2/knos_oidc/src/lib.rs::tests::a_key_header_can_never_read_as_a_verified_token`
- Replay of an old attestation: refused an hour after its `exp` (75); inside that hour RegisterKey works once per key (the account exists afterwards, 67) and Refresh only sets `max(expires_at, now + KEY_TTL)`. Same test; `T::test_refresh_moves_the_expiry_to_thirty_days_from_now_and_never_earlier`
- An attestation signed by a key that is revoked, expired, not approved or still waiting: Step refuses to verify it (78, 77, 76), on every call, so a verification begun earlier stops too. `T::test_revoke_is_for_ever`, `T::test_a_key_past_its_expiry_verifies_nothing_until_github_names_it_again`, `T::test_an_attested_key_verifies_only_after_its_delay_and_the_guardians_approval`. (One verified before the key stopped: see the defect below.)

Key policy

- Using an attested key early: it needs the day and the guardian's approval, both (76); the program is stricter than "a day unless the guardian approves sooner". `T::test_an_attested_key_verifies_only_after_its_delay_and_the_guardians_approval`
- A key past its expiry, a second registration to get a new life, the guardian approving an expired key: refused (77, 67, 77). `T::test_a_key_past_its_expiry_verifies_nothing_until_github_names_it_again`
- Refresh to shorten a wait, approve, or move an expiry earlier: it writes `expires_at` only, never earlier. `T::test_refresh_moves_the_expiry_to_thirty_days_from_now_and_never_earlier`
- Approve or Revoke by anyone else, by the guardian's address without its signature, with extra data, or on an account that is not a key: refused (79, 68). `T::test_only_the_guardian_approves_and_revokes_and_it_can_do_nothing_else`
- Undoing a revocation by Approve, Refresh, RegisterKey, KeyParams or time: refused (78, 78, 67, 69); the account stays, so the hash cannot be registered again. `T::test_revoke_is_for_ever`
- Genesis: only GitHub's four hashes, each under issuer 0 only; the same modulus under GitLab's issuer, GitLab's own keys and any other key need an attestation (73). `T::test_a_genesis_key_verifies_at_once_and_only_githubs_four_keys_are_genesis`
- The test keys, test rotate pin, test repository and test guardian in the real build: absent. `T::test_the_real_build_trusts_none_of_the_test_values`, `programs-v2/knos_oidc/src/lib.rs::tests::the_attester_is_the_pinned_account_and_its_two_repositories`

Accounts

- Write to an address not derived from the payer and the id, or with another program in the system program's place; RegisterKey to an address not derived from the issuer and the modulus's hash; a payer that did not sign in Write, Step, Close, RegisterKey, KeyParams, Refresh: refused (67). `T::test_nothing_computed_for_one_token_serves_another_and_no_account_stands_in_for_another`, `T::test_refresh_moves_the_expiry_to_thirty_days_from_now_and_never_earlier`
- A token account, a wallet or another program's account in a key's place (Step, KeyParams, Refresh, Approve, Revoke), and a key account in a token's place: a token's third byte is at most 16 where a key's is 64 or 128, and the lengths are checked (68; KeyParams answers with invalid instruction data). `T::test_nothing_computed_for_one_token_serves_another_and_no_account_stands_in_for_another`, `T::test_wrong_montgomery_constants_are_refused`, `T::test_only_the_guardian_approves_and_revokes_and_it_can_do_nothing_else`
- Writable flags: every account the program writes is written through the runtime's own check; no instruction trusts a flag it does not test.

Clock

- A token past its `exp` still verifies (Step asks nothing about lateness, by design); every use of it here asks `fresh` (an hour past `exp`, 75). `T::test_every_condition_of_the_attestation_is_needed_to_register_a_key_and_to_refresh_one`, `T::test_no_token_outlives_its_key_by_more_than_25_hours_whatever_expiry_it_carries`
- `iat` and `nbf` are not read here: nothing in this program orders tokens by them.

### The verifier: defects found and fixed

- A revocation (or an expiry) did not end what the key had already verified. `exp` is whatever the key's holder signs, Step accepted any `exp`, and RegisterKey and Refresh ask only whether the attestation is within an hour of its `exp`. So the holder of a leaked GitHub key could verify one attestation with an expiry years away before the guardian revoked the key, and use it afterwards for as long as he liked: measured on the old build, Refresh of another key 29 and 58 days after the revocation, and RegisterKey of his own key 58 days after it (that key still needs the guardian's approval). Fix: the finishing Step refuses `exp > now + AHEAD` (86,400 s, error 63), so no token account passes `fresh` more than AHEAD + LATE (25 hours) after its key was last usable. No instruction's bytes or accounts changed; fixtures rebuilt and pinned. `T::test_no_token_outlives_its_key_by_more_than_25_hours_whatever_expiry_it_carries`, `programs-v2/knos_oidc/src/lib.rs::tests::a_token_verified_while_its_key_was_usable_is_fresh_for_at_most_25_hours_more`

### The claim reader: strict since 2.2

- **The defect (2.1 and before).** The claim reader found the claims it wanted and stepped over every other value by its brackets and quotes. So a payload the issuer's key really signed, and that a JSON library refuses, verified: a literal cut short (`tru`), a number with a leading zero, brackets that do not match, a control character or bytes that are not UTF-8 in a string, `NaN`, a comment. This project's differential test found it (13 shapes, 342 cases in the run recorded for 2.1, every one accepted by the program and refused by the reference). Nobody without the issuer's key can make such a token, and GitHub and GitLab sign JSON. What it cost: two readers of one verified payload could disagree about it.
- **The fix (`knos_oidc` 2.2, [`strict.rs`](../programs-v2/knos_oidc/src/strict.rs)).** Every byte of the header and of the payload is checked against RFC 8259 as it is read, the values nobody asked for too: the literals are `true`, `false` and `null`; a number follows the grammar; a string is valid UTF-8 with JSON's escapes only, no control character, and no half of a surrogate pair written as an escape; brackets match, each with its own kind; nothing follows the object. Three things the RFC leaves to the reader are decided the strict way: a name that appears twice in the top-level object is refused (error 62) whether or not anyone reads it, compared as the text it spells; a document is at most 64 levels deep; its top-level object has at most 128 members (error 61 for both). The token account's layout, every instruction's bytes and accounts, and every error code are 2.1's.
- **Where the fix is, and why there.** In a file of its own that only the verifier's own instructions call: Step reads the header and the payload with it before it marks the token account VERIFIED. [`claims.rs`](../programs-v2/knos_oidc/src/claims.rs), the reader a program that spends a token compiles in (`knos_pay` depends on the `knos_oidc` crate by path), is 2.1's source byte for byte, and the crate's version stays 0.3.14: either change would change the bytes of `knos_pay`, which 0.3.16 does not change. The lenient reader needs no fix of its own, because a payload the strict reader refuses is never VERIFIED, and a VERIFIED account is all a consumer reads: no such payload ever reaches it. On every document the strict reader accepts, the two readers must find the same claims (`tests/claims_random.rs` and `fuzz/src/lib.rs` hold them to that). So the program says which it is by `knos_oidc::VERSION` and by `source_release: knos-oidc 2.2` in its `security.txt`, not by its crate's version.
- **That the other three programs did not change, by building them.** Measured here on 2026-10-05, each built from this tree with the command `scripts/build_programs_v2.sh` uses for its test fixture and compared with the committed fixture of 0.3.15 (`tests/fixtures/SHA256SUMS`): `knos_pay_v2_test.so` the same, sha256 `575f1d38…a714`, 405,240 bytes; `knos_passkey_v2_real.so` the same, `d2047d8a…c9f7`; `knos_meter_test.so` the same, `bff47b07…10d6`. The meter's build depends on where the checkout is (its interface crate is a path dependency outside the workspace): the committed hash came out of a checkout beside the build's target directory, of this tree and of 0.3.15's commit alike, and from two other directories the two gave each other's bytes again (`d24476cd…d5e7` both in one of them). One committed file is not what its own commit builds: `knos_pay_v2_nodevnet.so` built from 0.3.15's commit or from this tree is `5f51327a…7698`, one byte from the committed file (a line number in a panic location: the file was built a source line earlier and not rebuilt). The default-feature builds of `knos_pay` and `knos_meter`, which have no committed file, are also the same from this tree as from 0.3.15's commit. With the `knos_oidc` crate's version moved to 0.3.16 and nothing else, `knos_pay_v2_test.so` was the same size and differed in 905 bytes: that is why the version did not move.
- **What it costs in compute units.** Less than before, because the verifier decodes base64 with a table now (in the same file: the decoder in `claims.rs` is 2.1's, and the verifier no longer calls it). Measured in LiteSVM with one payer, the 2.1 test build against the 2.2 one, the two transactions of a 2048-bit verification (plan 8 and 8 squarings): the standard test token (a GitHub token of 1,893 bytes) 768,895 and 851,129 before, 764,637 and 829,670 after; the largest GitHub-shaped token the tests make (8,192 bytes) 804,540 and 1,174,864 before, 800,266 and 1,051,303 after. A 4096-bit token still takes six. The costliest payload we could build for the strict reader (8,191 bytes, 128 members, the rest an array of one-digit numbers, under a 4096-bit key) takes 1,293,728 in its last transaction, and 1,294,514 with every name written with an escape (a few thousand more or less with the payer, whose address decides how long the token account's address takes to find), of the 1,400,000 a transaction has: `T::test_the_plans_fit_the_longest_token_the_program_takes`.
- **How it is tested.** `strict.rs::tests::every_value_is_json_whether_or_not_anyone_reads_it` and `a_document_is_at_most_64_deep_and_its_object_has_at_most_128_members`; `tests/claims_random.rs` and `fuzz/tests` (the reader against `serde_json` on 1,560,000 random documents, both directions: what one refuses the other refuses; and the consumers' two readers against it on every document it accepts); the differential test below; the token, order and meter tests against the new verifier build and the unchanged builds of `knos_pay`, `knos_meter` and `knos_passkey`.
- **Its size.** A verified 2.2 build that `program.yml` made in staging on 2026-10-05, from the release tree before its last staging fixes, was 170,912 bytes, sha256 `44ba0a0419f8a95799da84de7906c8453467b21ceea33889a1bae73b781fc932` (2.1: 162,104). A later change to the program's source can move both: the verified build of the release commit is the one that counts. The verifier's program data account on devnet has room for 279,360 bytes (asked of devnet on 2026-10-05), so the upgrade needs no extension.
- **Until it is live.** 2.2 will be proposed after the pending upgrade executes, through the multisig with the public 48-hour delay like every upgrade. Until that proposal has executed, the verifier on devnet is an earlier build (2.0 until proposal 3 executes, 2.1 after it), and both take the thirteen shapes. The live state is in [`web/upgrades.json`](../web/upgrades.json).

### The verifier: left open (not changed)

- The 25 hours above remain for a consumer that does not take the key account. They are closed for the verifier's own attestations: since 2.1 RegisterKey, RegisterIssuerKey and Refresh take the key account that verified the attestation and require it to be usable now (`test_an_attestation_counts_only_while_the_key_that_verified_it_is_usable`). `knos_pay` and `knos_meter` take the key account for every token.
- `knos_oidc` 2.1, like the 2.0 build before it, does not check that a payload is JSON in the values it does not read, and one of the two runs on devnet until a 2.2 proposal has executed (see "The claim reader: strict since 2.2" below). [`web/upgrades.json`](../web/upgrades.json) says which build is live.
- 2.2's reader has limits of its own, which are part of what it accepts: 64 levels of nesting, 128 members in the top-level object, and a name is compared with the others in the top-level object only (a name twice inside a nested object is not looked for). A token past a limit is refused with error 61.
- `knos_pay` 2.1 and the interface crate still carry the reader that passes over unread values, and so does `knos_oidc`'s own `claims.rs`, kept as it was for them. They read only payloads the verifier has verified, so under 2.2 they are never given a document the strict reader refused; under 2.1 they can be.
- The committed test build `knos_pay_v2_nodevnet.so` is one byte from what its own commit builds, and `knos_meter`'s bytes depend on the directory the checkout is in (see "That the other three programs did not change" above). Neither file was touched: 0.3.16 changes no file of those programs. To compare a program with the chain, build the commit its proposal names (`source_commit` in [`web/upgrades.json`](../web/upgrades.json)) the reproducible way (`solana-verify`), which fixes the directory.
- `idl/knos_oidc_v2.json` was not edited (no bytes or accounts changed): its text for Step and for error 63 does not mention the bound on `exp`.
- A token from a job whose `exp` is more than a day ahead (possible only for an issuer that lets a token live that long) is refused until the bound is met; GitHub's tokens are far inside it.
- A genesis hash that nobody registered can be registered at any later time with a full KEY_TTL and no attestation, and the guardian cannot revoke a key that has no account. `pins.rs` says to register all four at deployment; if one is ever left out, the guardian has to register and revoke it itself.

### The payment program: reviewed and found sound

Tests named in this part are in `tests/test_pay2_chain.py` unless a Rust file is given.

Account substitution
- A forged job, another user's bind, record or pair, another mint, its vault, the other token program, a wrong `auth`, a wrong `rent_to` in Pay: every account is re-derived from the job's own fields or the token's payee, and a job is read only at the address its fields derive. `test_pay2_chain.py::test_a_job_is_not_paid_with` (38 cases).
- The same in FundBalance (baltok, mint, vault, auth, token program, pause, job, a non-Balance as the Balance): `test_pay2_chain.py::test_a_comment_does_not_fund_with`; in FundWallet: `test_pay2_chain.py::test_a_wallet_does_not_fund_with`.
- Refund to a thief, to another Balance, to the wallet that opened the Balance, with a wrong vault, auth, rent account, mint or token program: a Balance's job goes only to that Balance's token account, a wallet's job only to a token account of that wallet. `test_pay2_chain.py::test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from`.
- Withdraw or SetBalance by anyone but the wallet that opened the Balance, or to a token account that wallet does not own: `test_pay2_chain.py::test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance`, `test_pay2_chain.py::test_only_the_wallet_that_opened_a_balance_changes_its_cap_and_spenders`.
- One kind of account read as another (a Balance as a job, a key account as a token): lengths differ, each is read at its own PDA, and a verifier key account never has the VERIFIED stage byte. `state.rs::layouts_do_not_overlap_and_fill_their_lengths`, case "a token account of the verifier's in place of the key" of `test_a_job_is_not_paid_with`.
- A token program that is neither SPL Token nor Token-2022, or not the mint's owner: `mint_of` runs before every CPI to it. `token.rs::a_mint_is_a_mint_of_the_token_program_passed`, `test_pay2_chain.py::test_a_mint_is_a_mint_of_the_token_program_passed_and_harmless_extensions_are_accepted`.
- A missing signature (relayer, authority, guardian): cases in `test_a_proof_pays_nothing_after_the_deadline_and_no_job_twice`, `test_an_issue_has_one_job_per_balance_and_a_relayer_must_sign`, `test_the_guardian_pauses_new_funding_only_and_nobody_else_can`.

Replay of a signed token
- A fund token twice, or out of order: `iat` must be later than the Balance's last. `test_pay2_chain.py::test_a_fund_token_works_once`.
- A fund token against another Balance (so another mint or another wallet's money): the audience names one Balance by address. `test_pay2_chain.py::test_a_fund_token_spends_only_the_balance_it_names`, `gh.rs::a_fund_audience_names_one_balance_as_solana_prints_it`.
- A comment in a repository another account owns, or by someone who is not the owner or a listed spender: `test_pay2_chain.py::test_a_comment_in_another_owners_repository_cannot_spend_a_balance`, `test_pay2_chain.py::test_only_the_owner_and_the_listed_spenders_spend_a_balance`.
- A pay token against another repository, another issue, other terms, the other mode, another workflow repository or commit: cases of `test_a_job_is_not_paid_with`.
- A pay token against a job funded after it was issued (a job re-created at the same address after a payment or refund included): `not_before`. Case "a token issued before the funding" of `test_a_job_is_not_paid_with`.
- One pay token paying several jobs on the same issue: it does, when they pin the same workflow and terms. This is the documented design, and each job pays the payee the proof names. `test_pay2_chain.py::test_one_proof_pays_every_job_on_the_issue_that_pins_the_same_workflow_and_terms`.
- A first-deployment token (`knos:` audience) or one kind of audience used as another: every parser requires `knos2` and its own word, with an exact number of fields. Cases "a first-deployment audience", "a pay audience", "a bind audience", "a first-deployment claim audience" of the three refusal tests.
- A bind token twice or an older one after a newer: `test_pay2_chain.py::test_a_wallet_is_not_bound_with` (case "an older token than the bind's"), `test_pay2_chain.py::test_nobody_binds_a_wallet_for_someone_else`.
- A GitLab token, an unverified token, a verified token's bytes in an account the verifier does not own: cases of `test_a_job_is_not_paid_with`.

Time bounds and the verifier's key
- `iat` more than 300 seconds ahead, `exp` more than an hour after `iat`, a token more than an hour past expiry: cases "a token from the future", "a token that claims to live for hours", "an expired token" of `test_a_job_is_not_paid_with`. Claim numbers have at most 18 digits, so the casts to i64 cannot wrap.
- `run_attempt` other than 1 for funding and binding: cases "a re-run of the commenter's run" (`test_a_comment_does_not_fund_with`) and "a re-run of the owner's run", "a re-run of the first push" (`test_a_wallet_is_not_bound_with`). A re-run of a proof is accepted on purpose.
- A token whose key was revoked or has expired, or passed with another key account: `test_pay2_chain.py::test_a_token_is_refused_once_its_key_is_revoked`, `test_pay2_chain.py::test_a_token_is_refused_while_its_key_is_expired_and_works_again_once_the_key_is_refreshed`, `test_pay2_chain.py::test_a_token_is_taken_only_with_the_key_account_it_names`.

Arithmetic
- Fee, cap and amount: `fee_of` cannot overflow and never exceeds the amount; amounts are bounded 1_000_000..=100_000_000_000 units (1.00 to 100,000.00 at 6 decimals, on devnet); the record's counters saturate. `lib.rs::the_fee_is_two_and_a_half_percent_with_a_floor_and_never_more_than_the_amount`, `test_pay2_chain.py::test_a_cap_per_job_is_enforced`, cases "less than the smallest bounty", "more than the largest bounty" of the two funding refusal tests.
- A job credited with more than its vault received: the job stores the vault's balance after the transfer minus before. `test_pay2_chain.py::test_a_random_walk_keeps_every_vault_equal_to_its_open_jobs`, `test_pay2_chain.py::test_tokens_sent_to_a_vault_directly_belong_to_no_job_and_stay_there`.

Token-2022
- Funding in a mint with a transfer fee now or scheduled, a transfer hook program, NonTransferable, or new accounts frozen: refused wherever money enters. `test_pay2_chain.py::test_no_money_enters_in_a_mint_that_is`, `token.rs::the_extensions_that_could_block_or_tax_a_payout_are_refused_and_no_other`.
- A mint with a permanent delegate, confidential transfers, an empty hook and a zero fee (the regulated stablecoins): accepted, works end to end; the issuer's powers stay the issuer's and change no job. `test_pay2_chain.py::test_a_token_2022_stablecoin_with_its_usual_extensions_works_end_to_end`, `test_pay2_chain.py::test_a_mints_issuer_keeps_its_powers_over_the_vault_and_the_job_waits`.
- A mint that turns bad after funding: no new money enters, money in escrow still leaves, the vault is debited exactly the job's amount. `test_pay2_chain.py::test_a_mint_that_turns_bad_takes_no_new_money_and_money_in_escrow_still_leaves`.
- A mint posing as a token account or the reverse, a multisig-sized account: the account type byte and the lengths are checked. `token.rs::a_token_account_is_read_only_from_its_own_program`.

Destinations
- A destination owned by someone else, in another mint, or the vault itself; a fee account that is not FEE_OWNER's: cases of `test_a_job_is_not_paid_with`.
- A frozen destination, or one that does not exist: nothing moves (the fee neither), the job stays open, and the same proof pays once the account can receive. `test_pay2_chain.py::test_a_frozen_or_missing_destination_moves_nothing_and_one_transaction_takes_a_job_once` (added).
- A token account a stranger created and handed to the payee's wallet: paying into it is safe, because the token programs clear the delegate when an account changes owner, and a close authority cannot move tokens. By reading; no test.

Rent and closing
- Rent of a job sent to the relayer of the payment or refund instead of whoever paid it: `rent_to` must be the job's. Case "the rent sent to someone else" of `test_a_job_is_not_paid_with`; the lamports are asserted in `test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from`.
- A funding relayer (anyone: a fund token is public) who later turns the account the rent goes back to into a program, so that the job could never close: in the runtime the tests run, a program account can be credited, and the job is paid and refunded. `test_pay2_chain.py::test_a_job_is_paid_and_refunded_whatever_the_account_its_rent_goes_to_has_become` (added). Older runtimes refused to credit an executable account; that rule (SIMD-0162) is no longer among the pending activations of any cluster in Agave's feature gate tracker (read 3 Oct 2026). Worth one check on the target cluster before real money.
- A job paid twice, or paid and refunded, inside one transaction; a closed job revived by sending it lamports: the job is emptied and handed back to the system program in the instruction that pays it, so the next instruction finds no job. Same added test; `test_pay2_chain.py::test_a_proof_pays_nothing_after_the_deadline_and_no_job_twice`.
- Lamports sent to a job, vault, record, pair, bind or Balance address before it exists: `test_pay2_chain.py::test_an_address_that_was_sent_lamports_before_it_exists_is_still_created`.

Held payments, refunds, deadlines
- A held job taken by another proof, settled to a wallet the payee did not bind, settled with another user's bind, settled twice, or refunded during the hold: `test_pay2_chain.py::test_with_no_wallet_the_job_is_held_for_the_payee_and_paid_once_they_bind_one`, `test_pay2_chain.py::test_a_held_job_returns_to_the_funder_after_180_days_and_not_before`.
- A bind hidden by passing another account so that the token's address is paid instead: the account must be the payee's bind address. `test_pay2_chain.py::test_a_proof_pays_the_payees_bound_wallet_whatever_address_the_token_carries`.
- A refund before the deadline (its own second included), a payment after it, a refund after payment: `test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from`, `test_a_proof_pays_nothing_after_the_deadline_and_no_job_twice`.

Guardian
- A pause longer than 7 days, by anyone else, unsigned, or one that stops payments, settlements, refunds, binds or withdrawals: `test_pay2_chain.py::test_the_guardian_pauses_new_funding_only_and_nobody_else_can`. Pause writes one timestamp and sends no token instruction.

Bind
- Anything but a first-attempt `workflow_dispatch` run of the pinned claim workflow, started by the owner of a personal repository named knos-claim, on a GitHub-hosted runner: `test_pay2_chain.py::test_a_wallet_is_not_bound_with` (20 cases: other workflow file, repository or commit, push, schedule, comment, pull request, re-run, an organisation's repository, a name that only ends alike), `test_pay2_chain.py::test_nobody_binds_a_wallet_for_someone_else`.

Faucet
- Test USDC minted for a token that names a Balance of real money, or on a real-money build: `test_pay2_chain.py::test_the_faucet_mints_nothing_for_a_token_that_names_another_balance`, `test_pay2_chain.py::test_the_faucet_exists_once_and_the_real_money_build_has_none`.

By design, and not money (noted so nobody is surprised)
- A relayer who lands a later fund token of a Balance first makes the earlier one useless; the comment has to be made again. lib.rs says so.
- A funder can raise a payee's public record by paying that payee's id to a second wallet of the funder's own; it costs the fee. The record's self-payment rule sees only the funding wallet, the Balance's owner and the commenter.
- `default = ["devnet"]` in Cargo.toml: a real-money build needs `--no-default-features`. A devnet build on a real cluster would only add the faucet's own test mint.

### The payment program: defects found and fixed

none

## Reproduce it yourself

The tests. They run offline.

```
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
python -m pytest -q tests
```

Tests that need a toolchain skip and say so: the Go and Rust judge tests, the Node tests of the multisig scripts (Node 20 and `npm ci --prefix scripts`), and the check of every workflow with `actionlint`. To repeat the random walk with another seed: `KNOS_FUZZ_N=2500 KNOS_FUZZ_SEED=1 python -m pytest -q -s tests/test_pay2_chain.py -k random_walk`. The Rust tests, with the Wycheproof vectors: `cd programs-v2 && cargo test --release`.

**The instruction handlers, from Rust.** Besides the Python chain tests, a Rust crate drives the handlers of all four programs end to end (`cd programs-v2/handlers && cargo test`; the crate is outside the programs' workspace, because `cargo build-sbf` cannot read every manifest in `litesvm`'s dependency tree): `tests/knos_<program>.rs` loads the test binaries from `tests/fixtures` into the `litesvm` crate (0.7.1; signature checking on) and sends them the signed transactions of `programs-v2/testdata/*.json`, asserting each answer (accepted, or the instruction and the custom error that refused it), token balances and account fields. 16 tests; they ran in 6 to 20 seconds here once compiled, and the first compilation took 11 minutes on two shared cores. The program workflow runs them after it builds the binaries. The transactions are not built in Rust: `scripts/rust_test_vectors.py` writes them from the Python harnesses with wallets from a counter and tokens signed by the seed test key, so two runs write the same bytes (`--check` compares), and it must be run again when an instruction's accounts or data change. So this is a second virtual machine version and a second set of assertions over the same instruction builders, not a second client. Asserted from Rust: `knos_oidc` Write, Step (a token verified in two transactions; one bit of the signature flipped, error 70), RegisterKey, KeyParams; `knos_pay` FundOrderWallet, FundOrderBalance, PayOrder (paid once; the same token again, error 101 because the order is gone; the same address funded again and the old token shown, error 91 from its marker), RefundOrder (error 83 before the deadline, whole after it), Cancel (errors 80 and 83), and the fee at 100, 1,000, 1,001, 50,000 and 50,001 against `order_fee`; `knos_meter` OpenCredits, Record, RecordBatch (the same seq again, error 125), ClaimBatch, WithdrawCredits; `knos_passkey` Open and Withdraw (another passkey's signature: the precompile's error 2, and the program's 114; a replay, 119). Every other instruction has no Rust handler test and is tested from Python only: `knos_oidc` Close, Refresh, Approve, Revoke, RegisterIssuerKey and RegisterPrivateKey; `knos_pay` OpenBalance (it runs in every scenario's setup, asserted only as accepted), SetBalance, Withdraw, the job instructions (FundBalance, FundWallet, Pay, Settle, Refund), Bind, Pause, the faucet, Version, SetPlan, Release, Revert, Reserve, TopUp, Assign, BindOrg, SettleOrder, CloseMarker; `knos_meter` SetPlan, CloseMark, Version; `knos_passkey` Fund.

The drills on the deployed bytes, the upgrade drill and the replay. The first and the third read devnet and send nothing; the second starts a validator on this machine and needs the Solana command line tools, Node 20 and `npm ci --prefix scripts`.

```
python scripts/drills.py                                   # writes docs/DRILLS.md; exit 1 when a row fails
python scripts/drills.py --tokens tokens.jsonl --strict    # with real tokens; exit 1 also when a row was not run
KNOS_DRILL_LOG=upgrade.log bash scripts/drill_upgrade.sh --from-devnet
python scripts/replay_tokens.py --capture drexthealpha/knos-e2e --out tokens.jsonl
python scripts/replay_tokens.py --corpus tokens.jsonl
python -m pytest -q -s tests/test_wycheproof_chain.py
```

The programs. This needs `cargo build-sbf` on the path.

```
bash scripts/build_programs_v2.sh all
```

It runs five builds. Four are copied into `tests/fixtures/` and are what the chain tests load:

- `knos_oidc_v2_test.so` and `knos_pay_v2_test.so`: test builds (`--features testkeys`).
- `knos_pay_v2_nodevnet.so`: a test build with no faucet, the rules of a real-money build.
- `knos_oidc_v2_real.so`: `knos_oidc` with no features.

The fifth, `knos_pay` with default features (the devnet build), is left in `programs-v2/target/deploy/knos_pay.so`. The script copies and pins nothing else. It and `solana-verify` both write to `programs-v2/target/deploy/` unless `CARGO_TARGET_DIR` names another folder for the script, so the later build overwrites the earlier.

`tests/fixtures/SHA256SUMS` has ten lines. Four pin those binaries. Six pin data files: one under `docs/`, one under `tests/data/`, and four fixtures of the interface crate. The script rewrites the lines of the binaries it built. `tests/test_fixtures_pinned.py` fails when a pinned file changes, and when a `*_v2_*.so` in `tests/fixtures/` is not pinned. A changed binary then shows up in review as a changed pin.

The pins do not tie the deployed program to the source. The script says the deployed binary is not its output but the `solana-verify` build, and `program.yml` says a plain `cargo build-sbf` differs from it because toolchain paths are embedded. So a rebuild on another machine can change the pins without anything being wrong. In CI, the committed test binaries are deleted before the build, so the chain tests load only what that commit's source built.

To compare a deployed program with the source, make the reproducible build with the command `scripts/deploy_v2.sh` and the `verified-build` job of `program.yml` run, from the root of a clone. It needs docker.

```
rm -f programs-v2/target/deploy/knos_pay.so programs-v2/target/deploy/knos_oidc.so
solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name knos_pay --base-image solanafoundation/solana-verifiable-build:2.3.11
solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name knos_oidc --base-image solanafoundation/solana-verifiable-build:2.3.11
solana-verify get-executable-hash programs-v2/target/deploy/knos_pay.so
solana-verify get-program-hash -u devnet 5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k
```

The paths are whole (`"$PWD"`), not `.`. solana-verify finds the manifest with `find <mount>` and removes the mount's text from each path it lists, so a mount of `.` removes every dot and hands cargo `programs-v2/knos_pay/Cargotoml`, which it refuses. The repository is mounted, not `programs-v2` alone, because `knos_meter`, a member of that workspace, reads `crates/knos-oidc-interface`. `programs/` holds the first deployment's `knos_pay` and `knos_oidc` under the same names, and solana-verify builds the first manifest `find` lists: its line `Building manifest path` must name `programs-v2/<name>/Cargo.toml`. On a file system that lists `programs` first (NTFS, so WSL under `/mnt/c`), it builds the first deployment's crate, and the `rm -f` line makes `get-executable-hash` fail rather than hash an older file: build from a clone on a Linux file system. `tests/test_program_ci.py` checks that this command, `deploy_v2.sh`'s and `program.yml`'s are the same.

The hash from `get-executable-hash` and the hash from `get-program-hash` must be equal. Do the same for `knos_oidc` and `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W`. Without `solana-verify`, dump the program and hash it yourself:

```
solana program dump 5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k out.so --url devnet
python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read().rstrip(b'\x00')).hexdigest())" out.so
python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read().rstrip(b'\x00')).hexdigest())" programs-v2/target/deploy/knos_pay.so
```

The trimming matters. `deploy_v2.sh` deploys with `--max-len` of twice the program's size, so a program deployed that way ends in zero padding. `solana-verify`'s hash ignores trailing zero bytes, and `elf_hash` in `src/knos/mainnet_check.py` does the same. `KNOS_VERIFIED_DIR=programs-v2/target/deploy knos mainnet-check` makes this comparison for both programs, on the line "on-chain bytes are this repository's verified build". Its other gates read the upgrade authority, the multisigs and the guardian from the chain, and its last gate, an outside review, fails today on purpose.

## Fuzzing, mutation testing and model checking: the state of each

- **The differential test of the verifier.** `tests/test_oidc_differential.py` runs the built program (the test build, in LiteSVM, each token written and stepped) against a reference that shares no code with it: for the signature, OpenSSL and RFC 8017 section 8.2.2 on Python integers, which must also agree with each other; for the header and the claims, Python's `json` and a rule the file's first lines state. The corpus is made from seed 20261005. The recorded run, on 2026-10-05, against the test build of `knos_oidc` 2.2 with sha256 `a88034e9f1d342c57b2d2822db309aa36412d9762d74d55c4dde022c075454a1`: 8,855 cases, 1,301 accepted by both, 7,554 refused by both, 0 disagreements, 0 accepted with an invalid signature. `python tests/test_oidc_differential.py --cases 8855 --record` repeats it (it took 150 seconds here; the run recorded for 2.1 was 13,677 cases in ten minutes, and a run that long has not been made of 2.2), and [fuzz.json](fuzz.json) has the counts by kind of refusal. No class of token is outside the rule any more: the thirteen shapes of a signed payload that is not JSON in a value the verifier does not read, which 2.1 accepted and the reference refused, are kinds of the corpus like any other (1,131 cases of them in the recorded run, and 258 more of other ways not to be JSON, a name twice and half a surrogate pair), and the program refused every one. The same file asks the reference alone about Project Wycheproof's 517 vectors under their own keys. What it is not: the test build trusts the two seed keys, so the arithmetic runs under two moduli; and the rule is this project's (RFC 8259, and three places where JSON readers differ decided the strict way), so agreement with it is not agreement with every JSON reader there is.
- **Coverage-guided fuzzing.** `programs-v2/knos_oidc/fuzz` holds two cargo-fuzz targets. `claims`: any bytes at all, read by both copies of the claim reader and by `serde_json`. Since `knos_oidc` 2.2 the program's reader must accept exactly the documents `serde_json` reads as one object (less a name twice at the top level, more than 64 levels and more than 128 members; a number too large for `serde_json`, such as `1E400`, is the one case left to the program alone), every wanted claim must agree, and the interface crate, which reads only what the program verified, must read every document the program accepts the same way. `rsa_verify` (new in 0.3.15): any bytes as a modulus, a digest and a signature, put to the program's `rsa.rs`, to big integers and to the `rsa` crate; the three verdicts must agree, and where the program takes the modulus the whole value s^65537 mod n is compared; in its second form the fuzzer writes the encoded message and a test key signs it, which is how a wrong encoding is reached. Both start from committed seeds (`fuzz/seeds`, 575 files: every kind of the differential test, the thirteen shapes of not-JSON that 2.1 accepted among them, and Wycheproof's vectors), which `cargo test` also runs on stable. The `fuzz-claims` job of `program.yml` runs each target for five minutes on the nightly schedule and when started by hand, and publishes, as artifacts of that run and not as commits, a line per target (executions, files in the corpus, crashes) in `fuzz_targets.jsonl` and `fuzz.json`, the corpus (`fuzz-claims-corpus`) and any crash (`fuzz-claims-crash`). The latest nightly run tried 16,024,654 inputs against the claim parser. No nightly run has included `rsa_verify` yet: its only runs so far are by hand, here, on 2026-10-05 (120 seconds a target: `rsa_verify` tried 8,406 inputs and `claims` 4,413,242, with no crash; the numbers are in [fuzz.json](fuzz.json)). Those runs were of the 2.1 reader. The 2.2 reader has had no coverage-guided run yet: what it has had is the target's own check under `cargo test` on stable (1,260,000 documents made at random from fixed seeds, 200,000 strings of noise and the 575 seeds, no disagreement), and the differential run above. `rsa_verify` is slow, about 70 inputs a second under the sanitizer, because every input costs several big-integer powers. No target has been run for longer than five minutes at a time.
- **Random walks.** Not coverage-guided: random instructions with a conservation check after every step. Four walks of 2,500 steps over `knos_pay`'s 2.0 instructions run in `program.yml` on every change and nightly ([BENCH.md](BENCH.md)); the walks over work orders run in the default suite.
- **Wycheproof through the on-chain path.** `tests/test_wycheproof_chain.py` runs the vectors through the compiled program's `Step`, not only through the one-call form.
- **Mutation testing.** `scripts/mutants.sh` runs cargo-mutants over `knos_pay` and `knos_oidc` (it changes the source one small piece at a time and runs the Rust unit tests on each). It takes hours, so it is not in the default suite; the release run starts it and publishes the count of mutants caught and missed in [BENCH.md](BENCH.md). Until that run finishes there is no number, and none is claimed. One hand-run of 16 mutations of the judge rule was caught 16 of 16 by `tests/test_order_judges.py`.
- **Model checking.** `programs-v2/knos_pay/src/proofs.rs` holds Kani harnesses (run nightly by `program.yml`). One run is recorded in docs/kani.json (Kani 0.68.0, each harness alone, 180-second limit): four of five verified, among them fee conservation; the fee-bounds harness timed out twice and is not proved by that record. What they state: a payment's tip and fee bookkeeping creates and loses nothing (verified), and for every u64 amount the order fee stays between its floor and its cap (the harness that timed out). The five harnesses, by name: `the_remainder_of_a_share_is_never_more_than_the_remainder`, `an_orders_fee_is_between_its_floor_and_the_first_tiers_rate_for_every_amount`, `a_payment_takes_its_share_of_the_amount_and_of_the_fee_and_the_last_one_empties_the_order`, `what_a_funder_puts_in_is_what_the_payees_the_relayer_and_the_fee_owner_take_out`, `an_order_that_has_paid_nothing_has_given_out_none_of_its_fee`. All five are about `knos_pay`'s money arithmetic. None is about the verifier. Two properties did not come back from the solver and are NOT model-checked: that payees' shares never exceed the payment, and that the fee given out grows with what was paid. Those two are covered by randomised tests in the same file and by the random walks only.
- **What nothing proves.** There is no formal proof of the RSA arithmetic: `rsa.rs` is Montgomery multiplication written by hand, and what stands behind it is tests (Wycheproof's vectors, the differential runs, the fuzz target), which show agreement on the inputs tried and nothing about the rest. No model checker has been run on `knos_oidc`. And no outside reviewer has read the verifier, or anything else here.
- **A replay corpus of real tokens.** `scripts/replay_tokens.py` captures real GitHub tokens with the key set of their day and verifies them again on the deployed bytes. The release run makes the file. None is committed, and no real token has been replayed by the tests.

## A known false rejection: a fix that adds a test

Measured in [TAMPER.md](TAMPER.md): of 48 honest submissions, the black-box judge accepted 39. All 9 refusals are one
kind: a correct fix that also adds a regression test in the protected test directory. The judge refuses any pull
request that touches a protected path, so it refuses these too. That is the judge working as written, and it is a
false rejection of honest work.

The workaround, until the judge tells an added test from a changed one:

- say what is protected yourself: `protected = [...]` in `.knos/proof.toml` replaces the judge's list, so a list
  without the test directory lets a pull request add a test there (it also lets one change a test: the acceptance
  checks in `.knos/acceptance/` stay protected only if the list names `.knos/**`);
- or ask for new tests in a second pull request;
- or fund the task in merge mode, where a maintainer's merge and the named checks decide.

The order's `paths:` term does not lift this: it narrows what a pull request may change, and the protected list is
applied as well.

## Where an outside reviewer should start

These are the places where a mistake costs money. They are not a scope for an audit; a reviewer should set that. Read first, now: `programs-v2/knos_pay/src/order_judge.rs`. It is one function, `judge`, and it decides who may sign a payment of a work order. It is new in 0.3.13, it is the rule the seller's own settlement rests on, and nobody outside has read it. Then `order_pay.rs` and `order_terms.rs`, where an order's money leaves. Then the five below, which are older.

**1. The RSA arithmetic.** `programs-v2/knos_oidc/src/rsa.rs`, called from `Step` in `lib.rs`. It is Montgomery multiplication written by hand on 32-bit limbs, split over several transactions, followed by a byte-for-byte check of the PKCS#1 v1.5 encoding. The Wycheproof vectors run through `verify_native`, the one-call form of the same arithmetic. The stepwise on-chain path is checked by the 120 OpenSSL verdicts and the forgery list, and since 0.3.13 by the same 517 vectors carried over to tokens (`tests/test_wycheproof_chain.py`): that run uses the two test moduli, not the vectors' own. Since 0.3.15 a differential test puts forged tokens of every classic kind to the built program and to a reference, and a second fuzz target compares the arithmetic with big integers under moduli the fuzzer chooses (both above). None of this is a proof. Only 2048- and 4096-bit keys and exponent 65537 are handled. A mistake that accepts one forged signature lets anyone make a token of their own look verified. They could then pay every open bounty to a wallet of their choice, and fund bounties from any balance within its cap per bounty.

**2. The claim parser.** `programs-v2/knos_oidc/src/strict.rs` (what the verifier reads a token with since 2.2), `programs-v2/knos_oidc/src/claims.rs` (what a consumer reads a verified one with), and its use in `programs-v2/knos_pay/src/gh.rs`. It decodes base64url, splits the token and finds named claims in flat JSON without a JSON library. The `aud` claim is text a workflow chooses, so it is text the attacker may write inside the signed JSON. Since 0.3.13 the file has unit tests of its own, a randomised comparison with `serde_json` under `cargo test`, and a cargo-fuzz target that a nightly job runs for five minutes (above). A mistake lets a token signed for one repository or workflow be read as another's, which moves money that is not the signer's. The first deployment's copy of this file is older and is not fuzzed.

**3. Token-2022 extension screening.** `extensions_ok` and `ALLOWED` in `programs-v2/knos_pay/src/token.rs`. When money enters, the extension list is walked as (type, length, value), and the mint is refused unless every type is on the list of ten. A list that does not parse is refused. The tests make mints with Token-2022 instructions in LiteSVM, in the version it bundles, and try every type from 1 to 64 that is not on the list. A mistake lets money into a mint whose behaviour blocks or taxes payouts. Each order has its own token account, so other orders are not touched.

**4. The off-chain decision of who is paid.** `payee`, `payout_address` and `rejected` in `src/knos/who.py`; `evidence` and `accepted` in `src/knos/terms.py`; `src/knos/closing.py`; and `settle` in `src/knos/flow.py`, the command that decides and then asks GitHub for the token. The program checks that the bounty's own repository ran its pinned workflow, and then pays the payee that workflow named. It cannot check who earned the money, or whether the checks passed. The tests use fakes of GitHub's API, so what GitHub really answers (edit stamps, lists of closed issues, collaborator permissions, check-run listings) is what the authors assumed it answers. A mistake pays the wrong person, or pays for work whose checks did not pass. The payment is final at once, with no veto. It is limited to that funder's own bounties. That a funder's repository can lie is a known limit ([SECURITY.md](SECURITY.md)), not a finding.

**5. The key registration attestation.** `attested` in `programs-v2/knos_oidc/src/lib.rs` and the constants in `programs-v2/knos_oidc/src/pins.rs`. The program checks which file ran, at which commit, in which of the pinned account's two repositories, on which event and on which kind of runner, and that `aud` names the key's hash. The workflow it names, `drexthealpha/knos-oidc-rotate` at commit `6ddf031b64febecfcd510763ecee37637a8047fa`, is not in this repository, which holds only the calling file `.github/workflows/keys.yml`. What that workflow asks GitHub to sign is its own reading of the issuers' key sets, so a reviewer has to read it at that commit. The same repository holds `claim.yml`, which `Bind` trusts at the commit in `CLAIM_SHA` of `programs-v2/knos_pay/src/lib.rs`. The tests sign these claims themselves, with a seed key and a harness account. They cannot run the pinned workflow or the real account, because only GitHub can sign for those. A Rust test checks that the harness values exist only under `testkeys`. A mistake admits a key that GitHub does not publish. Whoever holds it can sign any token. The one-day delay and the guardian's approval are then all that stand between that key and every bounty. `python scripts/oidc_pins.py` prints the hashes of the keys the issuers publish right now, to compare with the four `GENESIS` constants in `pins.rs`. Its `--check` flag reads the first deployment's `pins.rs`, not this one.
