"""Names vulture cannot see being used, each with the reason it exists. CI runs:

    vulture src/knos scripts --min-confidence 60

Everything else vulture would report is deleted, not listed here.
"""
# ruff: noqa
from knos import cli, sdk
from knos.jobs import cli as jobs_cli, worker
from knos.pro import cli as pro_cli
from knos.team import cli as team_cli

_ = object()

# Typer registers these with decorators and calls them when a person types the command.
cli._no_command, cli.guard_cmd, cli.private_cmd, cli.mcp_cmd, cli.help_cmd
cli.memory_export, cli.memory_import, cli.memory_note
jobs_cli.list_, jobs_cli.sibyl_cmd, jobs_cli.relay_cmd, jobs_cli.serve_cmd, jobs_cli.stats_cmd
pro_cli.spend, pro_cli.budget_show, pro_cli.budget_set, pro_cli.report_cmd, pro_cli.budget_chain_show
pro_cli.budget_revoke, pro_cli.budget_raise, pro_cli.budget_clear, pro_cli.budget_fund, pro_cli.budget_agents
pro_cli.budget_sweep, pro_cli.pay_cmd, pro_cli.pro_status, pro_cli.pro_buy, pro_cli.pro_check, pro_cli.pro_activate
team_cli.agent_record, team_cli.prove, team_cli.mirror

# http.server.BaseHTTPRequestHandler calls these by name (board, Actions server, relay).
_.do_GET, _.do_POST, _.do_PUT, _.do_OPTIONS, _.log_message

# Library attributes set for their side effects: sqlite3 rows by name, shlex splitting, the Windows console API.
_.row_factory, _.whitespace_split, _.dwSize

# The public Python SDK (docs/INTEGRATE.md, examples/langgraph_team.py) and what Worker.once() returns to callers.
sdk.Knos, sdk.Knos.holder_of, sdk.Knos.memory_client, worker.Outcome.delivered

# 0.3.4: the escrow's fee rule and pause switch, used by the escrow tests and the operator; the proof verdict's
# failures (used by the replay); the Sibyl store keeps its Memory open for its lifetime.
_.fee_for, _.set_paused, _.failures, _._mem

# 0.3.5: `knos verify` is registered by its typer decorator; a verdict's `settled` is what the CLI prints.
_.verify_cmd, _.settled

# 0.3.6 escrow: the stake rule and a settled job's state are read by the tests and by clients; the LiteSVM harness's
# token-account helper is used by the escrow tests.
_.stake_for, _.is_closed, _._tok

# 0.3.7: the bounty, faucet and multi-mint builders and the GitHub proof constants are used by the escrow tests, the
# web wallet's twin in JS, scripts/register_github_keys.py and clients; the LiteSVM harness records CU and logs for
# the tests that print them.
_.bounty_brief, _.post_bounty, _.faucet, _.init_faucet_mint, _.add_mint, _.GH_BUF_LEN, _.GH_ISSUER
_.GH_WORKFLOW_PREFIX, _.gh_audience, _.last_cu, _.last_logs

# 0.3.8: a caught tamper is learned by the prove judge (knos.jobs.prove), which calls history.learn_tamper.
_.learn_tamper

# 0.3.8: the authority hand-over and workflow-pin builders are run by scripts/squads_handover.mjs's Python twin, the
# tests and the operator; `knos mainnet-check` is registered by its typer decorator.
_.mainnet_check_cmd, _.set_admin, _.set_fee_account, _.WF_FUND, _.set_workflow

# 0.3.9: the issuer-registry, FundWithToken audience and program-version builders are used by the escrow tests
# (tests/test_fund_issuer.py, tests/test_escrow_idl.py) and by clients registering a GitLab issuer.
_.CLAIMS_GITLAB, _.register_issuer, _.fund_audience, _.version_ix
