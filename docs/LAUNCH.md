# Launch: the twenty checks before strangers arrive

A common pre-launch list for a web product, answered for Knos one item at a time. Knos has no accounts, no
passwords, no email and no AI provider of its own. Where an item does not apply, the row says why in one sentence and
names the nearest thing Knos does have, with its test. Everything is on Solana devnet with test USDC.

`python scripts/launch_check.py` reads this table and exits 1 when a file or a test named in the evidence column is
missing, when the tree holds a key (`scripts/secret_scan.py`), or when the site or the package gains an analytics
script, an email sender or an AI provider. `--history` also scans every blob ever committed (about a minute);
`--launch-day` also fails while any row is not done.

Status words: **done**; **partly** (what exists, and the rest is in the last column); **not done**; **not applicable**
(with the reason). Evidence: a test as `file::test`, a file, or a command.

| # | item | status | evidence | not done |
|---|---|---|---|---|
| 1 | no API key in the frontend or in git | done | `scripts/secret_scan.py`, `tests/test_secret_scan.py::test_a_key_deleted_from_the_tree_is_still_found_in_history_by_kind_without_its_value`, `.gitignore`; the site holds no key: `web/` is scanned with the tree | nothing |
| 2 | rotate any key ever committed | done | `python scripts/secret_scan.py --history`: one real key in history, a Solana program keypair, see "Keys found in history". It is spent, and the scan fails if its address ever becomes one Knos operates with, review or not: `tests/test_secret_scan.py::test_a_reviewed_key_whose_address_becomes_operated_must_be_rotated` | the key stays in history: git history cannot be changed for everyone |
| 3 | rate limiting, so one user cannot burn the bill | done | `knos record serve` keeps a token bucket per client and answers 429 with Retry-After: `tests/test_record_api_safe.py::test_past_the_limit_a_client_gets_429_with_retry_after_and_others_are_served`, `tests/test_record_api_safe.py::test_a_token_bucket_per_client_refills_at_its_rate`; the faucet: `tests/test_faucet.py::test_the_daily_cap_holds_for_everyone_together`, `tests/test_faucet.py::test_one_grant_per_account_and_per_address_in_seven_days`; the relay: `tests/test_ghrelay.py::test_a_passkey_funding_line_on_an_issue_is_sent_by_the_worker_and_answered` (20 a day per repository) | nothing |
| 4 | auth on every route, not just the UI | done | every route of `knos record serve` is listed with who may call it, and anything else is 404: `tests/test_record_api_safe.py::test_every_route_is_stated_and_answers_as_stated_and_nothing_else_is_served`; the programs check every signer: `tests/test_pay_chain.py::test_nobody_can_claim_another_accounts_money`, `tests/test_pay_chain.py::test_every_wrong_proof_is_refused` | nothing |
| 5 | data rules, so users see only their own data | done | there are no user accounts; one self-hosted tenant never reads another's records: `tests/test_record_api_safe.py::test_two_tenants_sharing_a_memory_folder_see_only_their_own_records_and_counts`; money is held per account: `tests/test_pay_chain.py::test_nobody_can_claim_another_accounts_money`. The public record page shows public chain data and public pull requests by design: `docs/PRIVACY.md` | nothing |
| 6 | validate every input on the server | done | the record API checks length, charset and shape and answers 400 with one line: `tests/test_record_api_safe.py::test_a_bad_input_is_400_with_one_line_saying_why`, `tests/test_record_api_safe.py::test_a_grant_of_the_wrong_shape_is_refused_before_it_is_used`; the programs: `tests/test_pay_chain.py::test_terms_are_bounded_and_the_real_money_build_has_no_faucet`, `tests/test_oidc2_chain.py::test_every_forgery_is_refused`; `tests/test_selfhost.py::test_bad_config_is_refused_with_a_reason` | nothing |
| 7 | a spending cap on the AI provider | not applicable | Knos calls no AI provider; an agent calls its own model with its own key, and calls Knos through its MCP tools: `src/knos/mcp.py`; `scripts/launch_check.py` fails if the package imports a provider's client | nothing |
| 8 | errors never leak stack traces | done | an HTTP answer is one line, the trace only on the operator's terminal: `tests/test_record_api_safe.py::test_an_unforeseen_error_is_a_500_with_one_line_and_the_trace_only_on_the_operators_terminal`; the CLI says one line unless `--debug` or KNOS_DEBUG=1: `tests/test_record_api_safe.py::test_the_cli_says_one_line_and_shows_the_trace_only_with_debug`, `tests/test_cli_help.py::test_a_wrong_command_line_is_one_line_and_exit_2` | nothing |
| 9 | error tracking before users tweet | partly | no tracker: the site makes no third-party request. What watches: `.github/workflows/watchdog.yml` restarts a relay with no heartbeat (`tests/test_worker_chain.py::test_the_watchdog_starts_a_chain_only_when_none_is_queued_or_in_progress`); the canary's runs: `docs/OPERATIONS.md` | nothing tells a person when the relay stops: the watchdog restarts it and opens no issue |
| 10 | back up the data and test a restore | done | back up: `knos archive make FILE.zip --events LOG --ledger L --statement S --sealed YYYY-MM-DD`; restore: unzip it and run `python verify.py` inside; backed up, deleted, restored, and the statements are byte-identical: `tests/test_backup_restore.py::test_back_up_delete_restore_and_the_statements_are_byte_identical`. The record itself is the chain and the forge | no buyer has restored one |
| 11 | a 404 and a 500 page that do not look broken | done | `web/404.html` (the site's own, from any depth); the site is static on GitHub Pages, so its "500" is a data file that does not load: every page then says so in one line with a Reload button, `web/retry.js`; both in a browser: `tests/web/launch.mjs`, `tests/test_site_launch.py::test_the_404_page_privacy_and_a_data_file_that_does_not_load_in_a_browser` | nothing |
| 12 | works on a cheap Android phone | partly | at 360 x 740, the CPU slowed 4x, 1.6 Mbps down and 150 ms round trip: first paint 1,392 ms, the first screen usable at 1,829 ms (medians of 3): `docs/perf.json` (`android`), `tests/test_site_launch.py::test_a_cheap_android_phone_paints_and_can_be_used_within_three_seconds`; no page scrolls sideways from 320 px: `tests/test_site_overflow.py::test_no_page_scrolls_sideways` | measured in headless Chromium with that slowing, not on a phone |
| 13 | nothing takes more than 3 seconds to load | done | on that slowed profile the first screen is usable at 1,829 ms and the Console (#buy) is drawn 2,549 ms after it is opened: `docs/perf.json`, `tests/web/android.mjs`; every interaction p95 under 300 ms: `tests/web/perf.mjs` | the #buy figure is measured, not held to 3 s by a test |
| 14 | meta tags and an OG image so links look good on X | done | `web/index.html`, `web/brand/card.png`, `tests/test_site_launch.py::test_a_shared_link_has_every_tag_and_one_address`, `tests/test_site_launch.py::test_the_card_is_a_1200_by_630_png_of_the_site_drawn_from_the_brand` | nothing |
| 15 | privacy policy and terms | done | `web/privacy.html` (no cookies, no third-party request, nothing stored; devnet test software, MIT, no warranty, test USDC only), linked from every page's foot: `tests/test_site_launch.py::test_each_privacy_line_agrees_with_the_code`; `docs/PRIVACY.md` (what a payment makes public), `LICENSE` | no lawyer has read either |
| 16 | analytics to see where people drop off | partly | no analytics script, by design. Measured: the funnel in the site's `stats.json` (`scripts/network_stats.py`, `tests/test_network_stats.py::test_installed_is_the_public_repositories_whose_workflows_call_knos_and_not_knos_own`), the relay log (the issue labelled `knos-relay`, `.github/workflows/worker.yml`), PyPI download counts (pypistats.org, read by hand) | page views: not measured, and no tracker will be added |
| 17 | signup, payment and password reset tested end to end | not applicable | there is no signup and no password: a GitHub account and a comment fund work. Nearest, fund, pay, refund and the passkey wallet's withdrawal: `tests/test_pay_chain.py::test_a_comment_funds_a_devnet_bounty_with_test_usdc_and_no_wallet`, `tests/test_pay_chain.py::test_a_merged_pull_request_is_paid_to_its_authors_github_account_and_claimed_without_a_wallet_at_work_time`, `tests/test_pay_chain.py::test_with_no_proof_by_the_deadline_the_money_goes_back`, `tests/test_passkey_chain.py::test_a_wallet_is_paid_before_it_exists_and_one_transaction_opens_it_and_withdraws`; the passkey payee round the release runs on devnet: `tests/test_exercise_deployed_rounds.py::test_a_passkey_wallet_is_paid_before_it_exists_and_one_transaction_signed_by_the_passkey_opens_it_and_withdraws`, run at the public ids (`docs/capabilities.json`, `passkey_payee_wallet`: transaction 321WqsCL...) | the round's passkey was a key held in software, not a person's phone |
| 18 | emails do not land in spam | not applicable | Knos sends no email: every message is a comment on the forge, posted with the repository's own token (`src/knos/ghwords.py`); `scripts/launch_check.py` fails if the package gains an email sender | nothing |
| 19 | a way to contact the maker | done | `SECURITY.md`: private vulnerability reporting, switched on 10 October 2026 for this repository and for the 16 other public repositories of its owner whose name begins with knos (GitHub's API answers `enabled: true` for each), and issues for everything else; a contact line in `README.md`; on the site, `web/privacy.html`: report a problem in GitHub issues | nothing |
| 20 | a rollback plan for launch day | done | `docs/ROLLBACK.md`: PyPI, npm, the tag, the site, the relay and the programs, with the commands and who can run them | no drill of the whole page has been run |

## Launch day

`python scripts/launch_check.py --launch-day` fails today, and it should: three rows are partly. The check itself
holds (`python scripts/launch_check.py` exits 0). Each row closes only when its last column is done:

- **9, error tracking.** Closes when the watchdog tells a person each time it restarts the relay (a comment on the
  relay's issue), not only restarts it.
- **12, a cheap Android phone.** Closes when the founder opens the site on a real cheap phone and writes the times
  here.
- **16, analytics.** Stays partly by choice: Knos adds no tracker, so page views are not measured.

Row 19, contact, closed on 10 October 2026: private vulnerability reporting is switched on.

## The workflow-strip check on a personal repository

`knos protect --check-strip OWNER/REPO` (`src/knos/strip_check.py`) says closed, partly or open. Closed needs a
ruleset (a set of GitHub rules for a branch) that requires the Knos workflow. Partly means a required check names a
Knos check. The merge waits for that check, so removing the workflow alone blocks the merge. Still open: a pull
request can change the workflow that runs that check, and an admin can remove the requirement.

**On a personal repository, PARTLY is the most GitHub allows.** Only an organisation or enterprise ruleset on GitHub
Enterprise Cloud can require a workflow ([GitHub's list of rules, Enterprise Cloud edition](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging),
read 2026-10-10; the [Free, Pro and Team edition](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
has no such rule). On a personal repository GitHub refuses the rule with HTTP 422 "Invalid rule 'workflows'". That
happened on `drexthealpha/knos-witness` on 10 October 2026: its ruleset now requires the check `check / claims`, and
`knos protect --check-strip drexthealpha/knos-witness` reads PARTLY there. The same is said in `docs/ATTESTOR.md`.

A required check has a side effect. GitHub wants it to pass before any change reaches the branch
([GitHub](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging)),
so a direct push to that branch is refused too. To push straight to it, add yourself to the ruleset's bypass list.

## Keys found in history

`python scripts/secret_scan.py --history`, run on 9 October 2026 over every blob reachable from any ref of the
working copy (8,712 text blobs read; binary blobs and blobs over 20 MB skipped):

| kind | blobs | verdict |
|---|---|---|
| Solana keypair (64-byte array) | 1 | real: a program's deploy keypair, build output of `examples/oidc_gate` |
| AWS access key id | 4 | not a key: a made-up value in a test of redaction |

The keypair was never on `main` or on any published tag. Its address is named nowhere in the repository and holds no
role. It is treated as spent: no program is deployed at that address. Its blob id is
listed in `scripts/secret_scan.py` (`REVIEWED`), so a later scan names it as reviewed. The scan asks first whether its
address is one Knos operates with: if it ever becomes one, the scan fails, review or not. Any new hit fails the scan.

No GitHub, npm, PyPI or cloud token, and no PEM private key, was found in any blob ever committed.
