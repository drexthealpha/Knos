"""Names vulture cannot see being used, each with the reason it exists. CI runs:

    vulture src/knos scripts --min-confidence 60

Everything else vulture would report is deleted, not listed here.
"""
# ruff: noqa
from knos import cli
from knos.settle import pay as settle_pay

_ = object()

# html.parser.HTMLParser calls this for each tag it reads (scripts/test_one_product.py Links).
_.handle_starttag

# Typer registers these with decorators and calls them when a person types the command.
cli._main, cli.bounty, cli.due, cli.mainnet_check_cmd, cli.status_cmd
cli.balance_show, cli.balance_open, cli.balance_deposit, cli.balance_set, cli.balance_withdraw      # knos balance show | open | deposit | set | withdraw
cli.fund_wallet                                                                                     # knos fund-wallet
cli.receipt_check, cli.receipts, cli.export, cli.accept_init                                        # knos receipt check | receipts | export | accept init
_.rich_help_panel       # set on each registered command by the help's grouping in knos.cli; Typer reads it when it prints --help
_.judge_cmd, _.checks_hash, _.observe, _.lint, _.learn, _.gate, _.check, _.run
_.terms_cmd, _.evidence_cmd, _.memory_pull, _.memory_push, _.comment_cmd, _.closes_cmd
_.badge_cmd, _.record_cmd      # knos.badge.register: `knos badge`, `knos record`
_.command, _.settle, _.review       # knos command | settle | review | check: what a repository's workflow runs (knos.flow)

# The Sibyl store keeps its connection open for its lifetime.
_._storage

# knos.settle: the public client of knos-oidc and knos-pay. Constants mirror the programs' (clients and tests read
# them), and the dataclass fields are the accounts' layouts.
settle_pay.FAUCET_CAP, settle_pay.MAX_AMOUNT, settle_pay.MIN_AMOUNT, settle_pay.ERRORS
_.not_before, _.vetoes, _.done, _.exp, _.review, _.token_funded, _.funder_id, _.checks, _.wf_repo_hash, _.wf_sha

# knos.settle.v2.oidc: the public client of the second deployment of knos-oidc. Whoever keeps the keys alive sends
# Refresh, the guardian's multisig proposals carry Approve and Revoke, and a relay asks key_usable before it spends
# a fee; tests/test_oidc2_chain.py and tests/test_idl.py call them all.
from knos.settle.v2 import oidc as settle_oidc2

settle_oidc2.GUARDIAN, settle_oidc2.KEY_ADMIN, settle_oidc2.refresh_ix, settle_oidc2.approve_ix, settle_oidc2.revoke_ix, settle_oidc2.read_key, settle_oidc2.key_usable
# any RS256 issuer and private keys (knos-oidc 2.1): builders and readers for whoever admits or reads such a key
settle_oidc2.register_issuer_key_ix, settle_oidc2.register_private_key_ix, settle_oidc2.iss_pda, settle_oidc2.read_iss, settle_oidc2.token_issuer
settle_oidc2.Key.issuer_hash, settle_oidc2.Key.private, settle_oidc2.Key.registrant


# knos.settle.v2.pay: the public client of the second deployment of knos-pay. These five have no caller inside
# src/knos: scripts/settle_fixtures.py writes their bytes into sdk/settle/fixtures.json, which the JavaScript client's
# tests are held to, and scripts/governance_fixture.py (for scripts/governance.mjs) builds the guardian's Pause
# proposal from pause_ix and GUARDIAN. Listed here so that they stay if a script stops naming one.
from knos.settle.v2 import pay as settle_pay2

settle_pay2.GUARDIAN, settle_pay2.CLOCK_SLACK, settle_pay2.named_balance, settle_pay2.pause_ix, settle_pay2.init_faucet_ix

# What anyone may send for the second deployment with no token, and what another repository's workflow calls to hand
# its token to the public worker: both are the relays' public interface (tests/test_relay2.py, tests/test_worker.py),
# with no caller of their own in the worker's loop.
from knos.proof import ghrelay
from knos.settle.v2 import relay as settle_relay2

settle_relay2.register_missing, ghrelay.post_token

# http.server calls these on the request handler of scripts/acceptance_examples.py (the black-box service it stands up).
_.do_POST, _.log_message


# 0.3.14. Typer registers these inside each module's `register` and calls them when a person types the command.
_.receipt_cmd, _.make_cmd       # knos.bundle.register: knos receipt <file> | mirror | verify, knos bundle make (verify_cmd is named below)
_.rerun_cmd                     # knos.judge.register: knos judge rerun
_.export_, _.verify_            # knos.audit.register and knos.ledger.register: knos audit export | verify, knos meter verify | export
_.batch_, _.prove_, _.reconcile_        # knos.ledger.register: knos meter batch | prove | reconcile
# tarfile reads these off the TarInfo knos.bundle.make fills in: what makes two builds of one bundle the same bytes.
_.mtime, _.uname, _.gname
# The public client of knos_passkey 1.1's Fund and of the receipt format, with no caller inside src/knos: the tests hold
# them to the program and to the conformance vectors (tests/test_passkey_fund.py, tests/test_passkey_chain.py,
# tests/test_receipt.py), and web/passkey_fund.js is the browser's side of the same bytes.
from knos import receipt as receipt_
from knos.settle.v2 import passkey_fund

passkey_fund.fund_challenge, passkey_fund.rent_ixs, passkey_fund.intent_comment, passkey_fund.read_intent, receipt_.upgrade
# Which account of each token-taking instruction is the token's: tests/test_double_pay.py and tests/_pay2.py walk it.
settle_pay2.TOKEN_AT
# scripts/upgrade_feed.py writes `hash_from` into the feed's JSON for its reader.
_.hash_from

# 0.3.18. Typer registers these inside each module's `register` and calls them when a person types the command.
_.decide_                       # knos.decide.register: knos decide
_.migrate_                      # knos.ledger.register: knos meter migrate
_._propose                      # knos.terms_templates.register: knos terms propose
# The line by which a final receipt replaces a provisional one: the library's call for whoever holds both (docs/reference/RELAY.md),
# with no caller inside src/knos; tests/test_decide.py holds it.
from knos import decide

decide.supersede
# Typer registers these inside knos.agentkey's `register` and calls them when a person types the command.
_._init, _._rotate              # knos agent init | rotate


# 0.3.15. Typer registers these inside each module's `register` and calls them when a person types the command.
_.show_, _.check_, _.set_       # knos.controls.register: knos budget show | check | set
_.correct_, _.close_, _.statement_      # knos.ledger.register: knos meter correct | close | statement
_.observe_                      # knos.observe.register: knos observe
_.shadow_                       # knos.shadow.register: knos shadow
_._cite, _._verify              # knos.terms_templates.register: knos terms cite | verify (the registry of published terms)
# Python calls a module's own __getattr__ for a name the module does not have: `knos.cli.app` loads every command's
# module the first time someone asks for the whole command line by name (tests, scripts), and not before.
_.__getattr__
# The price table of the Buy page, as the Python computes it: tests/test_controls.py holds web/controls_data.js to it,
# row for row. And the size limits of the brand's files, which tests/test_brand.py reads from the tool that writes them.
from knos import controls as controls_

controls_.fee_table
_.BOUNDS


# 0.3.17. Typer registers these inside each module's `register` and calls them when a person types the command.
_.appeal_                       # knos.appeal.register: knos appeal
_.record_, _.status_            # knos.approvals.register: knos approve record | status
_.estimate_, _.explain_         # knos.billing.register: knos bill estimate | explain
_.card_, _.envelope_, _.offer_  # knos.controls.register: knos budget card | envelope | offer
_.ingest_, _.ack_, _.dupes_     # knos.events.register: knos events ingest | ack | dupes
_.preflight_, _.keep_           # knos.preflight.register: knos preflight | keep
_.make_, _.approve_             # knos.statement.register: knos statement make | approve
_.keygen_cmd, _.seal_cmd, _.open_cmd, _.export_cmd, _.restore_cmd, _.retain_cmd, _.checkpoint_cmd      # knos.vault.register: knos vault ...
# Public functions and constants with no caller inside src/knos or scripts: what a consumer of the package calls, each
# held by the tests (and the conformance kit) that name it.
from knos import badge as badge_, billing as billing_, ghwords as ghwords_, ledger as ledger_, pdf as pdf_, private as private_
from knos.settle.v2 import relayq as relayq_

badge_.verified_svg, badge_.verified_markdown       # examples/receipt_consumer/show_badge.py; tests/test_badge.py
billing_.PILOT, billing_.BOOK                       # the price book, as tests/test_billing.py holds it to tests/data/billing_vectors.json
ghwords_.program_code                               # tests/test_refusals.py
ledger_.billed_once                                 # conformance/impl/knos_python.py (conformance/vectors/ids.v1.json, ids.billed_once)
ledger_.reopened, ledger_.reopened_key              # docs/reference/METER.md; tests/test_verdicts_ids.py
pdf_.A4                                             # tests/test_statement.py
private_.receipt_shows                              # docs/reference/COMPANIES.md#private-repositories; tests/test_private_path.py
receipt_.exposed                                    # docs/reference/RECEIPT.md (the six questions); tests/test_verdicts_ids.py
relayq_.EVENT_TYPE                                  # the repository_dispatch type worker.yml listens for; tests/test_relayq.py holds the two together


# 0.3.19. Typer registers these inside each module's `register` and calls them when a person types the command.
_.take_                         # knos.advance.register: knos advance take
_.request_                      # knos.faucet.register: knos faucet request
_.add_, _.dispute_              # knos.netting.register: knos net add | dispute
_.grn_                          # knos.statement.register: knos statement grn
# http.server calls a handler's do_GET for each GET request (knos.record_api.serve: `knos record serve`).
_.do_GET
_.do_PUT, _.do_DELETE, _.do_PATCH, _.do_HEAD, _.do_OPTIONS       # the same for the other methods: each answers 405 in one line
_.server_version, _.sys_version                                 # http.server reads these for the Server header: no version is told
# Public functions and constants with no caller inside src/knos or scripts, each held by the tests that name it.
from knos import netting as netting_, record_api as record_api_

netting_.anchored                                   # whether the two knos_meter Ledger accounts anchor a period; tests/test_netting.py
record_api_.lookup                                  # the caller's side of a paid lookup, for an agent; tests/test_record_api.py
receipt_.LEVELS                                     # the assurance levels in rising order (receipt version 5); tests/test_assurance.py
settle_oidc2.revoke_es256_ix                        # ends a P-256 key (tag 14), for the guardian or the key's wallet; tests/test_es256_client.py

# 0.3.20. Typer registers these inside each module's `register` and calls them when a person types the command.
_.quote_                        # knos.advance.register: knos advance quote
_.compare_, _.policy_           # knos.archive.register: knos archive compare | policy
_.matrix_                       # knos.enforce.register: knos controls matrix
_.gaps_                         # knos.events.register: knos events gaps
_.reserve_, _.settled_          # knos.netting.register: knos net reserve | settled
_.exception_, _.queue_          # knos.recall.register: knos recall exception | queue
_._why, _._kinds                # knos.tasks.register: knos task why | kinds
# zipfile reads these of a ZipInfo when it writes the entry (knos.archive.pack: one date, no compression, one mode, so the same evidence is the same bytes).
_.compress_type, _.create_system, _.external_attr
# Public functions and constants with no caller inside src/knos or scripts, each held by the tests that name it.
from knos import rails as rails_, tasks as tasks_

rails_.accepted_rows                                # the rows a month's bill is made from, whichever rail paid; tests/test_statement_rails.py
tasks_.COUNTERS                                     # the counter each outside task kind moves, held to scripts/outsiders.py; tests/test_tasks.py
tasks_.kind_file                                    # tasks/outside/<kind>.json byte for byte; tests/test_tasks.py

# 0.3.21. Typer registers these inside each module's `register` and calls them when a person types the command.
_.bind_, _.release_, _.spend_   # knos.boundary.register: knos boundary bind | release | spend
_.sign_                         # knos.events.register: knos events sign
_.exit_                         # knos.exit.register: knos exit
_.keep_approval_, _.approval_, _.grant_, _.supplier_    # knos.recall.register: knos recall keep-approval | approval | grant | supplier
# Python looks a module's attributes up on its class: knos.settle.v2.relay sets its own module's __class__ so that a
# name set on the package reaches the part that holds it (a test's monkeypatch included).
_.__class__
# Public functions with no caller inside src/knos or scripts, each held by the tests that name it.
from knos import exports as exports_
from knos.proof import history as history_

billing_.release_split                              # a release's money, whose it is; tests/test_billing.py
billing_.floor_split, billing_.floor_remedy         # who earns what at the floor, and netting as its remedy; tests/test_billing.py
billing_.netting_example                            # what a small outcome pays alone and netted; tests/test_billing.py
exports_.parts_check                                # an export held to its parts file; tests/test_exports_parts.py
history_.grant_withdrawn                            # whether a buyer withdrew a supplier's grant; tests/test_history_defence.py

# 0.3.23. Typer registers these inside each module's `register` and calls them when a person types the command.
_.decisions_                    # knos.recall.register: knos recall decisions
_.accept_, _.refuse_            # knos.statement.register: knos statement accept | refuse
# http.server calls it for a folder (knos.selfhost.serve_site: no directory listing, a 404 instead).
_.list_directory
# Public functions with no caller inside src/knos or scripts, each held by the tests that name it.
from knos import ids as ids_

ids_.line_state                                     # the line state a word means, older words included; tests/test_line_states.py

# 0.3.24. Typer registers these inside each module's `register` and calls them when a person types the command.
_.assurance_                    # knos.assurance.register: knos assurance
_.plans_                        # knos.plan_floor.register: knos fees plans
_.protect_                      # knos.strip_check.register: knos protect
_.settle_sync_                  # knos.statement.register: knos statement settle-sync
_.complete_                     # knos.statement.register: knos statement complete
# Public functions with no caller inside src/knos or scripts, each held by the tests that name it.
_.relative_left                                     # scripts/bump_version.py: no link of README.pypi.md leans on the repository; tests/test_pypi_readme.py

# 0.3.26. knos.sources: a library a caller uses in its own code (docs/reference/VERIFIER.md); nothing in the package calls it yet.
from knos import sources as sources_
from knos.sources import der as der_

sources_.adapter                                    # the adapter by its name, and a plain refusal for any other; tests/test_sources.py
_.signed_at                                         # Evidence: when the log recorded the signature; tests/test_sources.py
_.sig_alg                                           # Cert: the certificate's signature algorithm, as its bytes give it
der_.ECDSA_SHA256, der_.ECDSA_SHA384                # the two signature algorithms' ids, named for the reader beside the key ids

# 0.3.29 to 0.3.34. Typer registers these inside each module's `register` and calls them when a person types the command.
_.game_                         # knos.game.cli.register: knos game
_.self_                         # knos.self.cli.register: knos self; knos.gate.cli.register: knos receipt self
_.init_, _.validate_, _.schema_, _.seal_, _.run_, _.require_    # knos.gate.cli.register: knos gate init | validate | schema | seal | run | require
_.keygen_, _.page_              # knos.gate.cli.register: knos receipt keygen | page
_.treasury_                     # knos.gate.cli.register: knos bounty treasury
_.get_cmd, _.search_cmd, _.in_cmd, _.who_cmd, _.sources_cmd, _.fields_cmd, _.wanted_cmd, _.check_cmd      # knos.ideas.cli.register: knos idea ...
_.commit_cmd, _.sign_cmd, _.release_cmd, _.refund_cmd, _.preorder_cmd, _.state_cmd                         # knos.ideas.cli.register: knos idea ...
_.works_cmd, _.makeable_cmd, _.maintainer_cmd, _.list_cmd, _.red_team_cmd      # knos.referee.cli.register: knos referee ... | knos cheats list | red-team
_.grade_cmd, _.rows_cmd         # knos.taskpack.cli.register: knos taskpack grade | rows
_.draft_, _.hash_, _.lock_, _.assign_, _.measure_, _.comment_, _.sample_, _.audiences_     # knos.outcomes.cli.register: knos outcome ...
_._calibrate                    # knos.tasks.register: knos task calibrate
# Hosts call these hooks with these argument names or positions; a hook takes them whether it reads them or not.
_.tool_use_id                   # knos.claude.agent_sdk.make_guard: the Claude Agent SDK calls a PreToolUse hook as (input_data, tool_use_id, context)
_.tool_name                     # knos.hermes_plugin.pre_tool_call: Hermes calls it with tool_name=..., args=...
_.redirect_request, _.newurl    # urllib calls HTTPRedirectHandler.redirect_request(req, fp, code, msg, headers, newurl) (knos.outcomes.data refuses every redirect)
_.protocol_version              # http.server reads it off the handler class (knos.mcp_http: HTTP/1.1, so a session keeps its connection)
# The lab adapters are built by name from the table in knos.labs (ADAPTERS: module and class name as strings).
_.Adaptyv, _.B12Selenium, _.B12Foundry, _.PCBWay, _.JLCPCB, _.MaterialsProject, _.Xometry
# Dataclass fields: the layout of an account, a message or a record, read by whoever holds one (and by the tests).
_.judge_backend, _.record_backend       # knos.autoresearch.loop.Report
_.timed_out                             # knos.autoresearch.sandbox.RunResult
_.explanation                           # knos.claude.managed.Run
_.quote_id, _.payment_methods           # knos.labs.base.Quote
_.failures                              # knos.leitner.Item
_.min_finality, _.destination_caller, _.finality_executed, _.burn_token, _.message_sender, _.expiration_block      # knos.money.cctp.Plan and Message (the CCTP V2 burn message)
_.payout_watermark                      # knos.money.x402_upto.Channel (state/channel.rs)
_.lamports_per_signature                # knos.platform.nonce.NonceAccount
_.attestation                           # knos.platform.sas.Verdict
_.last_reset                            # knos.platform.squads.SpendingLimit (the Squads v4 account)
_.recorder                              # knos.zk.client.Verdict (the program's verdict account)
# Constants that mirror a program's or a protocol's (clients and tests read them).
from knos.labs import base as labs_base_
from knos.money import cctp as cctp_, x402_upto as x402_upto_
from knos.outcomes import spec as outcome_spec_
from knos.platform import blockhash as blockhash_

labs_base_.SUBMITTED, labs_base_.IN_PROGRESS, labs_base_.QC, labs_base_.CANCELLED      # the states every lab's own words map to (STATES)
labs_base_.SPEC_FIELDS                              # the names of a Spec's fields; tests/test_labs_fields.py
cctp_.MESSAGE_TRANSMITTER_V2, cctp_.TOKEN_MESSENGER_MINTER_V2      # Circle's CCTP V2 programs on Solana, for whoever builds the receive side
x402_upto_.OPEN_SLOT_WINDOW                         # constants.rs of the upto program
outcome_spec_.ORDER_MIN_WHOLE                       # knos_pay ORDER_MIN_AMOUNT, in whole units
blockhash_.MAX_AGE_BLOCKS                           # the blockhash age limit of Solana; tests/test_platform_nonce_v34.py
# Public functions and constants with no caller inside src/knos or scripts, each held by the tests (or the program) that name it.
from knos import graduation as graduation_, ideas as ideas_, init as init_, playground as playground_
from knos.claude import managed as managed_
from knos.gate import app as gate_app_
from knos.ideas import wanted as ideas_wanted_
from knos.money import kora as kora_
from knos.outcomes import stats as outcome_stats_, synth as outcome_synth_
from knos.platform import claims as platform_claims_, referees as platform_referees_, verify as platform_verify_
from knos.proof import issuers as issuers_
from knos.receipt2 import ed25519 as receipt2_ed25519_
from knos.record import anchoring as anchoring_
from knos.repro import publish as repro_publish_
from knos.taskpack import atropos as atropos_
from knos.verify import sealed as sealed_
from knos.zk import bn254 as bn254_, client as zk_client_

managed_.agent_spec                                 # what client.beta.agents.create takes (src/knos/claude); tests/test_claude_agents_v34.py
gate_app_.verify_signature, gate_app_.app_jwt       # tests/test_gate_app.py
gate_app_.installation_token                        # github-app/server.py, the GitHub App's webhook server
graduation_.graduation_message                      # docs/reference/REFEREE_FROST.md; tests/test_verdict_trust.py
ideas_.FIXTURES_ENV, ideas_.intake                  # tests/test_ideas_sources.py, tests/test_ideas_contract.py
ideas_wanted_.ORACLE                                # tests/test_ideas_commit.py
_.OPT_IN_ENV, _.OPT_IN_WORD                         # knos.ideas.tools: the opt-in of the idea tools on `knos mcp` (KNOS_MCP_TOOLS=ideas); tests/test_ideas_tools.py
init_.posting_tools                                 # tests/test_agents_mcp.py, tests/test_host_hooks.py
_.lab_quote                                         # knos.labs.adaptyv.Adaptyv; tests/test_labs_adaptyv.py
_.box_number, _.due_orders                          # knos.leitner; tests/test_leitner.py
cctp_.attestation                                   # Circle's attestation of a burn; tests/test_money_kora_cctp.py
_.from_env                                          # knos.money.kora.Kora.from_env; tests/test_money_kora_cctp.py
kora_.gasless_ixs, kora_.send_gasless               # src/knos/money/kora.py; send_gasless: tests/test_money_kora_cctp.py
x402_upto_.withdraw_payer_ix                        # docs/reference/X402.md: the payer's way out of a channel
outcome_stats_.tiers_passed                         # tests/test_outcome_stats.py
outcome_synth_.drop_treated_failures, outcome_synth_.relabel, outcome_synth_.example_spec      # tests/test_outcome_measure.py, examples/outcomes/measured-support/demo.py
platform_claims_.shared_writable, platform_claims_.per_block      # docs/reference/PLATFORM.md; tests/test_platform_claims.py
platform_referees_.labelled                         # tests/test_labs_fix34b.py
platform_verify_.one_transaction_ixs, platform_verify_.fits_v1, platform_verify_.es256_v1_ixs     # docs/reference/PLATFORM.md; tests/test_platform_verify.py, tests/test_platform_es256.py
playground_.OLD_REPO                                # the playground's home until 0.3.34; tests/test_playground.py
issuers_.FORGE                                      # the judge kind 0 of order_proof.rs, named beside ATTESTED and PANEL
issuers_.TEST_ORCID_CLIENT, issuers_.orcid_of, issuers_.bind_orcid_ix, issuers_.proof_audience      # tests/test_proof_issuers.py
issuers_.cs_claims, issuers_.orcid_claims, issuers_.judge_of, issuers_.pay_order_proof_ix                          # tests/test_proof_issuers.py
receipt2_ed25519_.b58encode                         # tests/test_receipt2_sign.py
anchoring_.parse_memo                               # tests/test_record_verify.py, tests/test_record_devnet.py
repro_publish_.verify_signed                        # docs/reference/REPRODUCED.md; tests/test_repro_privacy.py
atropos_.referee_spec                               # docs/reference/REFEREE.md; tests/test_taskpack_export.py
sealed_.load_tasks, sealed_.public_prompt           # tests/test_hermes_gepa.py
bn254_.pairing, bn254_.G1_GEN, bn254_.G2_GEN        # src/knos/zk; tests/test_zk_groth16.py
zk_client_.DEVNET_PROGRAM_ID                        # the reserved devnet program id (src/knos/zk); tests/test_zk_client.py

# knos.settle.v2.passkey_smart: the LazorKit passkey wallet client. Its callers are the web app (apps/wanted/knos_wanted/
# wallets.py, preorder.py), outside vulture's scan (src/knos scripts); the constants mirror LazorKit's program (commit,
# authenticator flags, slot window, account discriminators) as the program's own source names them.
from knos.settle.v2 import passkey_smart as passkey_smart_
passkey_smart_.LAZOR_COMMIT, passkey_smart_.BE, passkey_smart_.BS, passkey_smart_.MAX_SLOT_AGE, passkey_smart_.D_WALLET
passkey_smart_.cred_hash, passkey_smart_.user_seed, passkey_smart_.create_wallet_ix, passkey_smart_.transfer_ownership   # wallets.py
passkey_smart_.table_addresses, passkey_smart_.create_table_ixs, passkey_smart_.read_table, passkey_smart_.wallet_table_addresses  # wallets.py (lookup tables)
passkey_smart_.message_v0, passkey_smart_.control_filters, passkey_smart_.sole_owner   # wallets.py; tests/test_passkey_smart_chain.py
# knos.threshold: the FROST referee coordinator and host-1 signer the web app runs (apps/wanted/knos_wanted/referee.py).
from knos.threshold import check as threshold_check_, ghoidc as ghoidc_, participant as participant_, session as session_
threshold_check_.verdict_record, ghoidc_.GH_HOST, participant_.LocalClient, session_.Coordinator   # referee.py; tests/test_threshold_*.py

# knos.threshold.codeattest: the app server's POST /api/referee/attest (apps/wanted/knos_wanted/referee.py, outside src/knos) checks
# the verdict, the token's claims and links the Rekor entry with these.
_.check_verdict, _.check_claims, _.rekor_url

# knos.demand_cli: `knos demand` is a Typer command; Typer calls it by its decorator, never by name.
_.demand_
# knos.ready.tranches: the app (apps/wanted valley.py, wallets.py) funds a long milestone's first 90-day order with it.
_.tranches
# scripts/trim_fonts.py: fontTools reads its subset.Options and TTFont settings as attributes (opts.flavor, opts.layout_features).
_.flavor, _.layout_features
