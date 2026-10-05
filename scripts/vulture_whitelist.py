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
# Typer registers these inside knos.agentkey's `register` and calls them when a person types the command.
_._init, _._rotate              # knos agent init | rotate


# 0.3.15. Typer registers these inside each module's `register` and calls them when a person types the command.
_.show_, _.check_, _.set_       # knos.controls.register: knos budget show | check | set
_.correct_, _.close_, _.statement_      # knos.ledger.register: knos meter correct | close | statement
_.observe_                      # knos.observe.register: knos observe
# Python calls a module's own __getattr__ for a name the module does not have: `knos.cli.app` loads every command's
# module the first time someone asks for the whole command line by name (tests, scripts), and not before.
_.__getattr__
# The price table of the Buy page, as the Python computes it: tests/test_controls.py holds web/controls_data.js to it,
# row for row. And the size limits of the brand's files, which tests/test_brand.py reads from the tool that writes them.
from knos import controls as controls_

controls_.fee_table
_.BOUNDS
