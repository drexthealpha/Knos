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
