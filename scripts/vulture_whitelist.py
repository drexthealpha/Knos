"""Names vulture cannot see being used, each with the reason it exists. CI runs:

    vulture src/knos scripts --min-confidence 60

Everything else vulture would report is deleted, not listed here.
"""
# ruff: noqa
from knos import cli
from knos.settle import pay as settle_pay

_ = object()

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

settle_oidc2.GUARDIAN, settle_oidc2.refresh_ix, settle_oidc2.approve_ix, settle_oidc2.revoke_ix, settle_oidc2.read_key, settle_oidc2.key_usable
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
_.margin_                       # knos.billing.register: knos bill margin
_.migrate_                      # knos.ledger.register: knos meter migrate
_._propose                      # knos.terms_templates.register: knos terms propose
# The line by which a final receipt replaces a provisional one: the library's call for whoever holds both (docs/RELAY.md),
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
ledger_.reopened, ledger_.reopened_key              # docs/METER.md; tests/test_verdicts_ids.py
pdf_.A4                                             # tests/test_statement.py
private_.receipt_shows                              # docs/PRIVATE.md; tests/test_private_path.py
receipt_.exposed                                    # docs/RECEIPT.md (the six questions); tests/test_verdicts_ids.py
relayq_.EVENT_TYPE                                  # the repository_dispatch type worker.yml listens for; tests/test_relayq.py holds the two together


# 0.3.19. Typer registers these inside each module's `register` and calls them when a person types the command.
_.take_                         # knos.advance.register: knos advance take
_.request_                      # knos.faucet.register: knos faucet request
_.add_, _.dispute_              # knos.netting.register: knos net add | dispute
_.grn_                          # knos.statement.register: knos statement grn
# http.server calls a handler's do_GET for each GET request (knos.record_api.serve: `knos record serve`).
_.do_GET
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

billing_.release_split                              # a release's money, whose it is (docs/UNIT_COSTS.md); tests/test_billing.py
billing_.support_hours                              # the support hours a budget buys (docs/UNIT_COSTS.md); tests/test_billing.py
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
