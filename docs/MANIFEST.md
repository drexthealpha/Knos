# Release manifest: Knos 0.3.18

**The neutral meter for AI agent work: neither side keeps the count.**

One page for this release: the source, the bytes each public program id runs, every capability's stage, and the
limits still open. `python scripts/release_manifest.py` writes it from the files named under each heading, and
`--check` fails when it differs from them. Nothing here is typed by hand, and no time is printed.

## Source

- Release: Knos 0.3.18 (`pyproject.toml`). Tag: [`v0.3.18`](https://github.com/drexthealpha/Knos/tree/v0.3.18); `git rev-list -n 1 v0.3.18` prints its commit. A file
  cannot hold the hash of the commit that holds it.
- Cluster: Solana devnet. The money is test USDC. Mainnet is not touched.

## Programs: what is live at each public id

Read from `docs/capabilities.json` (`programs`), `docs/provenance.json` (one read of the cluster; its `read` says
when) and `web/upgrades.json` (the multisig's accounts; its `generated` says when). A proposal that is pending has
not run: the public id runs the build in the third column until it does.

| program | public program id | LIVE at that id | hash at that id | its proposal | the proposal's verified build hash | built from |
|---|---|---|---|---|---|---|
| knos_oidc | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | knos_oidc 2.1 | `3758348d1051feab739b4dc776ffb597fe9ecef7d50e93abd3c460fa5e9f7d4d` (the proposal's build) | 3: executed | `3758348d1051feab739b4dc776ffb597fe9ecef7d50e93abd3c460fa5e9f7d4d` | [`6eb81dd`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5), run `37237561915` |
| knos_pay | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | knos_pay 2.1 | `2ed301a2bc99fc6e58abc0dcb767cb35e640898a75f154b2d90c09171143d507` (the proposal's build) | 4: executed | `2ed301a2bc99fc6e58abc0dcb767cb35e640898a75f154b2d90c09171143d507` | [`6eb81dd`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5), run `37237561915` |
| knos_meter | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | knos_meter 1.1 | `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4` (the proposal's build) | 5: executed | `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4` | [`6eb81dd`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5), run `37237561915` |
| knos_passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | knos_passkey 1.1 | `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81` (the proposal's build) | 6: executed | `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81` | [`6eb81dd`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5), run `37237561915` |
| upgrade_gate | `2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW` | upgrade_gate 1.0 | not read | none | none | none |

A program whose source changed after its proposal's commit has no verified build hash on this page until the
`verified-build` job has built it and a new proposal names it: `git diff <built from> -- programs-v2/<program>`
shows whether it changed. Each link of each chain is in [PROVENANCE.md](PROVENANCE.md).

## Pending proposals

Upgrade multisig `9HcsMEo2o6zZu9t1kbFWpnyKn7hiHaZYYFwNHZSpmWqK`, 2 of 3. From `web/upgrades.json`; when each can
execute is its `earliest_execution_utc` there.

None: web/upgrades.json lists no pending proposal.

## Capabilities: the stage of each, with its evidence

From `docs/capabilities.json`. A stage is the highest that has evidence; deployed and exercised count only at the
public program ids. The note of each capability and every lower stage's evidence are in
[CAPABILITIES.md](CAPABILITIES.md).

| capability | stage | evidence of that stage |
|---|---|---|
| `check` | tested locally | [`tests/test_proof.py`](../tests/test_proof.py) |
| `install_by_pull_request` | tested locally | [`tests/test_install_link.py`](../tests/test_install_link.py) |
| `terms_templates` | tested locally | [`tests/test_install_link.py`](../tests/test_install_link.py) |
| `stop_hook` | tested locally | [`tests/test_proof.py`](../tests/test_proof.py) |
| `mcp_tools` | tested locally | [`tests/test_mcp.py`](../tests/test_mcp.py) |
| `agent_tools` | tested locally | [`tests/test_agentkey.py`](../tests/test_agentkey.py) |
| `verify_github` | exercised on devnet | [4G2Zew7L...](https://explorer.solana.com/tx/4G2Zew7LgfNJ7v6KjaKceCFRRLBmK5LD7qYK3oUi58b9X3iMhR7dXD7oqr2FuNcvewy65R6N8k7iVD6JbrG5eJJV?cluster=devnet) |
| `verify_gitlab` | deployed on devnet | `knos_oidc 2.0` at its public id |
| `verify_any_issuer` | tested locally | [`tests/test_oidc2_chain.py`](../tests/test_oidc2_chain.py) |
| `key_guardian` | deployed on devnet | `knos_oidc 2.0` at its public id |
| `fund_by_comment` | deployed on devnet | `knos_pay 2.0` at its public id |
| `fund_from_wallet` | exercised on devnet | [4Q1cvM78...](https://explorer.solana.com/tx/4Q1cvM785mimadqAPQTwQyYWHBMZbFWzZ5W1w1zVQZsx3TUEKwesdyQoSimQCiUVJvUhUP6TFW9on5xLKzEn41sK?cluster=devnet) |
| `pay_on_merge` | deployed on devnet | `knos_pay 2.0` at its public id |
| `hold_and_bind` | deployed on devnet | `knos_pay 2.0` at its public id |
| `refund` | exercised on devnet | [57E3wRPG...](https://explorer.solana.com/tx/57E3wRPGfY34MFq89Uxi75AS9PMoCT7eFwnXgnfsFpVg9mbtoHB4FVJ5bYNMGLPANuvrYygwc32Su2W8jE5XtVeY?cluster=devnet) |
| `pause` | deployed on devnet | `knos_pay 2.0` at its public id |
| `work_orders` | exercised on devnet | [177CEpZ8...](https://explorer.solana.com/tx/177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet) |
| `order_pay` | exercised on devnet | [59AfaYHT...](https://explorer.solana.com/tx/59AfaYHTvWHhbAhiiNHCbCfEcGCxG1kCydJwfRNjZqry9bCnMF3ox6bd4P7favA9hjgzB5nk283g2Mdq3LruyNWV?cluster=devnet) |
| `tests_mode` | exercised on devnet | [55Gxtqyo...](https://explorer.solana.com/tx/55GxtqyoErGS6fJgJNNSe87qxJF3sUwgoZZkAQfTQ1eXQYhnqQaB861AQS6u1FXwuBBwY2dmQdWwgH9Zps1YfTVm?cluster=devnet) |
| `order_auto_accept` | exercised on devnet | [55Gxtqyo...](https://explorer.solana.com/tx/55GxtqyoErGS6fJgJNNSe87qxJF3sUwgoZZkAQfTQ1eXQYhnqQaB861AQS6u1FXwuBBwY2dmQdWwgH9Zps1YfTVm?cluster=devnet) |
| `order_challenge` | tested locally | [`tests/test_order_auto.py`](../tests/test_order_auto.py) |
| `order_quorum` | tested locally | [`tests/test_order_quorum.py`](../tests/test_order_quorum.py) |
| `hermetic_judge` | tested locally | [`tests/test_judge_hermetic.py`](../tests/test_judge_hermetic.py) |
| `holdback_release` | tested locally | [`tests/test_order_terms.py`](../tests/test_order_terms.py) |
| `warranty_revert` | tested locally | [`tests/test_order_terms.py`](../tests/test_order_terms.py) |
| `seller_settle` | tested locally | [`tests/test_order_judges.py`](../tests/test_order_judges.py) |
| `neutral_attest` | tested locally | [`tests/test_order_judges.py`](../tests/test_order_judges.py) |
| `arbiter_rule` | tested locally | [`tests/test_order_judges.py`](../tests/test_order_judges.py) |
| `reserve_cancel` | tested locally | [`tests/test_order_terms.py`](../tests/test_order_terms.py) |
| `top_up` | exercised on devnet | [432L2F98...](https://explorer.solana.com/tx/432L2F987ADLGHRPLuHMoULKQr8pYRMNyb9k2PAMZ5H7CJsix4JgqKbMHLx7yyY5kDmJnAt1Lb6fz5nMwEFhCCQJ?cluster=devnet) |
| `assign` | tested locally | [`tests/test_order_terms.py`](../tests/test_order_terms.py) |
| `advance_by_assignment` | tested locally | [`tests/test_advance.py`](../tests/test_advance.py) |
| `standing_order` | tested locally | [`tests/test_order_terms.py`](../tests/test_order_terms.py) |
| `org_balance_limits` | tested locally | [`tests/test_order_chain.py`](../tests/test_order_chain.py) |
| `org_wallet` | tested locally | [`tests/test_order_judges.py`](../tests/test_order_judges.py) |
| `plans` | tested locally | [`tests/test_order_chain.py`](../tests/test_order_chain.py) |
| `fee_tiers` | tested locally | [`tests/test_fees.py`](../tests/test_fees.py) |
| `single_use_tokens` | exercised on devnet | [177CEpZ8...](https://explorer.solana.com/tx/177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet) |
| `private_attestor` | tested locally | [`tests/test_flow_private.py`](../tests/test_flow_private.py) |
| `meter_single` | deployed on devnet | `knos_meter 1.0` at its public id |
| `meter_batch` | exercised on devnet | [4FxxZjQD...](https://explorer.solana.com/tx/4FxxZjQD8aqqTNRuiT3nS5e3Hh1f1UitCcRmfhBbMiiTj6w9wgRP5HDFUHicpXyCt5vmrue53oyGQM9unQgPWSzR?cluster=devnet) |
| `meter_seller_claim` | exercised on devnet | [3zJVYD2y...](https://explorer.solana.com/tx/3zJVYD2yxjz4vgi4NsED3cvjRnToboXdM9YPz2xyawkCUKcbUSNNY4rVhYuNMyNNY6LyTPwzFhrNzFdNn1i8N4Hc?cluster=devnet) |
| `passkey_payee_wallet` | deployed on devnet | `knos_passkey 1.0` at its public id |
| `passkey_funder` | exercised on devnet | [3oTzLPyD...](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) |
| `passkey_fund_relay` | exercised on devnet | [3oTzLPyD...](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) |
| `buyer_page` | exercised on devnet | [3oTzLPyD...](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) |
| `gitlab_pay` | tested locally | [`tests/test_gitlab_pay.py`](../tests/test_gitlab_pay.py) |
| `gitlab_ci_example` | implemented | [`examples/gitlab/.gitlab-ci.yml`](../examples/gitlab/.gitlab-ci.yml) |
| `relay` | tested locally | [`tests/test_relay2.py`](../tests/test_relay2.py) |
| `adapters` | tested locally | [`tests/test_adapters.py`](../tests/test_adapters.py) |
| `canary` | tested locally | [`tests/test_flow_orders.py`](../tests/test_flow_orders.py) |
| `load_local_1000` | tested locally | [`tests/test_load.py`](../tests/test_load.py) |
| `invariants_state_machine` | tested locally | [`tests/test_invariants_machine.py`](../tests/test_invariants_machine.py) |
| `rust_handler_tests` | tested locally | [`programs-v2/handlers/tests/knos_pay.rs`](../programs-v2/handlers/tests/knos_pay.rs) |
| `kani_fee_conservation` | tested locally | [`tests/test_provenance.py`](../tests/test_provenance.py) |
| `receipt` | tested locally | [`tests/test_receipt.py`](../tests/test_receipt.py) |
| `evidence_bundle` | tested locally | [`tests/test_bundle.py`](../tests/test_bundle.py) |
| `receipt_mirror` | tested locally | [`tests/test_bundle.py`](../tests/test_bundle.py) |
| `sas_receipt` | tested locally | [`tests/test_receipt.py`](../tests/test_receipt.py) |
| `x402_example` | tested locally | [`tests/test_x402_attested.py`](../tests/test_x402_attested.py) |
| `x402_knos_order` | exercised on devnet | [2noSVLKX...](https://explorer.solana.com/tx/2noSVLKXsSDc9iL72m6H4geVenuoDvrH7YiQ4FUEwLUYgEbWpqxk9TZxf6GQegSXCsZUR33GT2gn6HEUbkKTpwsX?cluster=devnet) |
| `cpi_fund` | tested locally | [`tests/test_cpi_fund.py`](../tests/test_cpi_fund.py) |
| `oidc_gate` | tested locally | [`tests/test_oidc_gate.py`](../tests/test_oidc_gate.py) |
| `upgrade_gate` | deployed on devnet | `upgrade_gate 1.0` at its public id |
| `upgrade_delay` | tested locally | [`tests/test_governance.py`](../tests/test_governance.py) |
| `upgrade_feed` | tested locally | [`tests/test_upgrade_feed.py`](../tests/test_upgrade_feed.py) |
| `policy` | tested locally | [`tests/test_flow_orders.py`](../tests/test_flow_orders.py) |
| `screening` | tested locally | [`tests/test_screen.py`](../tests/test_screen.py) |
| `statements` | tested locally | [`tests/test_records.py`](../tests/test_records.py) |
| `badge` | tested locally | [`tests/test_badge.py`](../tests/test_badge.py) |
| `audit_export` | tested locally | [`tests/test_audit.py`](../tests/test_audit.py) |
| `agent_pr_index` | tested locally | [`tests/test_agent_pr_index.py`](../tests/test_agent_pr_index.py) |
| `agent_weekly_rates` | tested locally | [`tests/test_agent_pr_index.py`](../tests/test_agent_pr_index.py) |
| `mainnet_check` | tested locally | [`tests/test_mainnet_check.py`](../tests/test_mainnet_check.py) |
| `deliverable_identity` | tested locally | [`tests/test_ledger_periods.py`](../tests/test_ledger_periods.py) |
| `meter_corrections` | tested locally | [`tests/test_ledger_periods.py`](../tests/test_ledger_periods.py) |
| `meter_period_close` | tested locally | [`tests/test_ledger_periods.py`](../tests/test_ledger_periods.py) |
| `ledger_dedup` | tested locally | [`tests/test_ledger_periods.py`](../tests/test_ledger_periods.py) |
| `receipt_five_parts` | tested locally | [`tests/test_receipt.py`](../tests/test_receipt.py) |
| `evaluator_independence_record` | tested locally | [`tests/test_receipt.py`](../tests/test_receipt.py) |
| `verify_without_chain` | tested locally | [`tests/test_receipt_offline.py`](../tests/test_receipt_offline.py) |
| `budget_controls_cli` | tested locally | [`tests/test_controls.py`](../tests/test_controls.py) |
| `console` | tested locally | [`tests/test_site_buyer.py`](../tests/test_site_buyer.py) |
| `observer_view` | tested locally | [`tests/test_observe.py`](../tests/test_observe.py) |
| `relay_journal_and_retries` | tested locally | [`tests/test_relay_failures.py`](../tests/test_relay_failures.py) |
| `dependency_drills` | tested locally | [`tests/test_drills.py`](../tests/test_drills.py) |
| `workflow_capacity_model` | tested locally | [`tests/test_capacity.py`](../tests/test_capacity.py) |
| `reproduction_kit` | tested locally | [`tests/test_reproduce.py`](../tests/test_reproduce.py) |
| `neutral_reexecution` | tested locally | [`tests/test_attest_rerun.py`](../tests/test_attest_rerun.py) |
| `doc_claims_check` | tested locally | [`tests/test_doc_claims.py`](../tests/test_doc_claims.py) |
| `agent_index_weekly_scan` | tested locally | [`tests/test_agent_pr_index.py`](../tests/test_agent_pr_index.py) |
| `opt_in_profiles` | tested locally | [`tests/test_badge.py`](../tests/test_badge.py) |
| `outcome_examples` | tested locally | [`tests/test_outcomes.py`](../tests/test_outcomes.py) |
| `knos_verify_action` | tested locally | [`tests/test_integrations.py`](../tests/test_integrations.py) |
| `webhook_verifier` | tested locally | [`tests/test_integrations.py`](../tests/test_integrations.py) |
| `agent_host_routes` | tested locally | [`tests/test_host_hooks.py`](../tests/test_host_hooks.py) |
| `oidc_differential` | tested locally | [`tests/test_oidc_differential.py`](../tests/test_oidc_differential.py) |
| `fuzz_rsa_diff_target` | tested locally | [`tests/test_oidc_differential.py`](../tests/test_oidc_differential.py) |
| `cli_lazy_start` | tested locally | [`tests/test_startup.py`](../tests/test_startup.py) |
| `site_cache` | tested locally | [`tests/web/live.mjs`](../tests/web/live.mjs) |
| `live_round_view` | tested locally | [`tests/web/live.mjs`](../tests/web/live.mjs) |
| `brand` | tested locally | [`tests/test_brand.py`](../tests/test_brand.py) |
| `shadow_mode` | tested locally | [`tests/test_shadow.py`](../tests/test_shadow.py) |
| `playground` | tested locally | [`tests/test_playground.py`](../tests/test_playground.py) |
| `interactive_demo` | tested locally | [`tests/test_site_demo.py`](../tests/test_site_demo.py) |
| `design_system` | tested locally | [`tests/test_site_overflow.py`](../tests/test_site_overflow.py) |
| `verifier_issuer_matrix` | tested locally | [`tests/test_issuers.py`](../tests/test_issuers.py) |
| `finance_exports` | tested locally | [`tests/test_exports.py`](../tests/test_exports.py) |
| `audit_export_v2` | tested locally | [`tests/test_audit.py`](../tests/test_audit.py) |
| `four_linked_objects` | tested locally | [`tests/test_audit.py`](../tests/test_audit.py) |
| `five_named_states` | tested locally | [`tests/test_flow.py`](../tests/test_flow.py) |
| `relay_stage_times` | tested locally | [`tests/test_ghrelay.py`](../tests/test_ghrelay.py) |
| `quorum_three_readers` | tested locally | [`tests/test_flow_quorum3.py`](../tests/test_flow_quorum3.py) |
| `outcome_orders` | tested locally | [`tests/test_flow_quorum3.py`](../tests/test_flow_quorum3.py) |
| `terms_registry` | tested locally | [`tests/test_terms_registry.py`](../tests/test_terms_registry.py) |
| `terms_memory` | tested locally | [`tests/test_flow_orders.py`](../tests/test_flow_orders.py) |
| `index_bounded_scan` | tested locally | [`tests/test_agent_pr_index.py`](../tests/test_agent_pr_index.py) |
| `honest_work_rate` | tested locally | [`tests/test_tamper_bench.py`](../tests/test_tamper_bench.py) |
| `provenance_chain` | tested locally | [`tests/test_provenance.py`](../tests/test_provenance.py) |
| `conformance_kit` | tested locally | [`tests/test_conformance.py`](../tests/test_conformance.py) |
| `release_registry_rule` | tested locally | [`tests/test_release_gate.py`](../tests/test_release_gate.py) |
| `oidc_strict_json` | tested locally | [`tests/test_oidc_differential.py`](../tests/test_oidc_differential.py) |
| `unwrap_inventory` | tested locally | [`tests/test_unwraps.py`](../tests/test_unwraps.py) |
| `outcome_not_code` | exercised on devnet | [31HzWxXF...](https://explorer.solana.com/tx/31HzWxXFoya7ZKphG9Tb9czvhKT9dZiCGP4F3sSvgkek9x7FLGATqsA1Mba45gpQpNFa8ELLcEUJyXCXZ2f92okk?cluster=devnet) |
| `events_ledger` | tested locally | [`tests/test_events.py`](../tests/test_events.py) |
| `ap_statement` | tested locally | [`tests/test_statement.py`](../tests/test_statement.py) |
| `four_verdicts_four_ids` | tested locally | [`tests/test_verdicts_ids.py`](../tests/test_verdicts_ids.py) |
| `relay_queue` | tested locally | [`tests/test_relayq.py`](../tests/test_relayq.py) |
| `evidence_vault` | tested locally | [`tests/test_vault.py`](../tests/test_vault.py) |
| `private_path` | tested locally | [`tests/test_private_path.py`](../tests/test_private_path.py) |
| `supplier_preflight` | tested locally | [`tests/test_preflight.py`](../tests/test_preflight.py) |
| `supplier_appeal` | tested locally | [`tests/test_appeal.py`](../tests/test_appeal.py) |
| `refusal_table` | tested locally | [`tests/test_refusals.py`](../tests/test_refusals.py) |
| `billing_rule` | tested locally | [`tests/test_billing.py`](../tests/test_billing.py) |
| `agent_leaderboard` | tested locally | [`tests/test_agent_pr_index.py`](../tests/test_agent_pr_index.py) |
| `front_door` | tested locally | [`tests/test_site_front_door.py`](../tests/test_site_front_door.py) |
| `es256_tokens` | tested locally | [`programs-v2/handlers/tests/knos_oidc_es256.rs`](../programs-v2/handlers/tests/knos_oidc_es256.rs) |
| `contributor_tests_not_counted` | tested locally | [`tests/test_tamper_bench.py`](../tests/test_tamper_bench.py) |
| `procurement_objects` | tested locally | [`tests/test_procurement.py`](../tests/test_procurement.py) |
| `approval_chains` | tested locally | [`tests/test_procurement.py`](../tests/test_procurement.py) |
| `fee_bounds_proofs` | tested locally | [`tests/test_fee_proofs.py`](../tests/test_fee_proofs.py) |
| `adversarial_replays` | tested locally | [`programs-v2/handlers/tests/adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs) |
| `reader_template` | tested locally | [`tests/test_reader_template.py`](../tests/test_reader_template.py) |
| `keyholder_path` | implemented | [`web/keyholder.js`](../web/keyholder.js) |
| `fee_one_rate` | tested locally | [`tests/test_fees.py`](../tests/test_fees.py) |
| `quorum_by_owner` | tested locally | [`programs-v2/handlers/tests/adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs) |
| `presentation_grace` | tested locally | [`programs-v2/handlers/tests/adversarial.rs`](../programs-v2/handlers/tests/adversarial.rs) |
| `commitment_format2` | tested locally | [`tests/test_ledger_format2.py`](../tests/test_ledger_format2.py) |
| `supplier_record` | tested locally | [`tests/test_record_page.py`](../tests/test_record_page.py) |
| `record_badge` | tested locally | [`tests/test_record_page.py`](../tests/test_record_page.py) |
| `invoice_receipt` | tested locally | [`tests/test_record_page.py`](../tests/test_record_page.py) |
| `supplier_install` | implemented | [`.github/workflows/supplier.yml`](../.github/workflows/supplier.yml) |
| `terms3_format` | tested locally | [`tests/test_terms3.py`](../tests/test_terms3.py) |
| `terms3_proposed` | tested locally | [`tests/test_propose_terms.py`](../tests/test_propose_terms.py) |
| `provisional_decision` | tested locally | [`tests/test_decide.py`](../tests/test_decide.py) |
| `relay_notes_merge` | tested locally | [`tests/test_relay_speed.py`](../tests/test_relay_speed.py) |
| `verdict_gate` | tested locally | [`tests/test_verdict_gate.py`](../tests/test_verdict_gate.py) |
| `agent_pays_agent` | tested locally | [`tests/test_agent_pays_agent.py`](../tests/test_agent_pays_agent.py) |
| `upstream_gate` | tested locally | [`tests/test_upstream_check.py`](../tests/test_upstream_check.py) |
| `claim_guard` | tested locally | [`tests/test_claim_guard.py`](../tests/test_claim_guard.py) |

## Outstanding limits

From [DISCLOSURE.md](DISCLOSURE.md), one line each.

- **No buyer has been interviewed.** Every statement here about what a buyer wants is the founder's reasoning from public sources ([MARKET.md](MARKET.md)).
- **No letter of intent.** Nobody has written that they would use or buy Knos.
- **No paying customer.** No price in the price book has been charged to anyone.
- **No pilot.** The [Pilot](PILOT.md) is an offer; nobody has bought it or been offered it.
- **No outside funder.** Knos's own account funded every task, in test money. Since 0.3.11, 3 payments have gone to another GitHub account, for three pull requests it wrote.
- **Outside key holders today: 0.** Both multisigs are 2-of-3 and one person holds all three keys ([KEYHOLDER.md](KEYHOLDER.md) says what changes it).
- **One founder, pseudonymous:** the GitHub account drexthealpha; no legal name is published.
- **No co-founder,** employee or adviser ([TEAM.md](TEAM.md)).
- **No legal entity.** Nothing can sign a contract, send an invoice or be sued as Knos, and there are no terms of service.
- **No legal advice taken.** [REGULATION.md](REGULATION.md) is what the founder read.
- **No outside review,** of the programs, the workflows, the relay, the clients, the site or the documents ([ASSURANCE.md](ASSURANCE.md)).
- **No shadow count.** The meter has never run beside anyone's invoices but Knos's own examples.
- **No outside program is known to read the verifier.** The interface and the examples are Knos's own ([COMPOSE.md](COMPOSE.md)).
- **No independent reproduction.** Nobody outside Knos has reported rebuilding the programs to the deployed hash, rerunning the benchmarks or running the drills.
- **The Rust crates and the npm package are not on crates.io or npm.** They install from this repository ([INSTALL.md](INSTALL.md)); the Python package is on PyPI.
- **No mainnet deployment.** Solana devnet and test USDC only; no real money has moved.
- **No second operator.** If the founder is unavailable, nobody answers a report, approves a key or cancels a proposal ([OPERATOR.md](OPERATOR.md)).
- **No organisation account.** The pinned workflows and the relay live in one personal GitHub account ([GOVERNANCE.md](GOVERNANCE.md), section 9).
- **The first deployment cannot be changed,** so its known limits stay ([SECURITY.md](SECURITY.md)); the second changes only through a multisig with a public 48-hour delay.
