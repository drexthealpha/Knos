# Check any of it in under a minute

Nothing here is a claim. Each row is a command; run it and see. This is
the long form of the short table in the README.

Nothing below is a claim. Each row is a command; run it and see.

| What | How to check it yourself |
|---|---|
| A claim changes what other agents are told | `knos claim "the parser"` — it prints the exact refusal your agents now get. `knos done` gives it back. |
| One agent's claim reaches another agent's **live** session, with no restart or cache | `pytest tests/test_no_network.py -k live_session` — one process claims, a second sees it on its next call |
| No network connection, ever | `pytest tests/test_no_network.py` — breaks `socket.connect`, `bind`, `create_connection`, `getaddrinfo`, then reads a repo, answers, writes, claims, withholds, overrides. A third test breaks the guard on purpose, so it cannot pass by doing nothing |
| Decisions you keep in the repo are read | `pytest tests/test_rules.py -k decisions_kept_beside` — an ADR answers with `docs/adr/0001-use-sqlite.md:3` |
| Every worktree of a repo is one memory | `pytest tests/test_worktrees.py` |
| A big repo is never half-read | `pytest tests/test_worktrees.py -k runs_out_of_time` — both readers, forced to time out, leave nothing behind |
| Secrets are invisible, not redacted | `pytest tests/test_private.py` — the search layer is asked directly, with an agent's identity |
| What dies when you delete the store | `pytest tests/test_sibyl_is_load_bearing.py -k number_status_prints` |
| Three MCP tools, no more | `pytest tests/test_recall.py -k three_tools_are_listed` |
| Two agents cannot both hold the same claim | `pytest tests/test_intent.py -k two_processes` — two real processes race for one topic; one wins, the other is told who has it |
| A crashed agent cannot hold work forever | `pytest tests/test_intent.py -k lapses` |
| A reworded question is withheld too | `pytest tests/test_intent.py -k paraphrased` — `the risk guard` is claimed, the question shares no word with it, the answer is still refused |
| A claim reaches the file it names | `pytest tests/test_intent.py -k reaches_the_file` — `the risk guard` covers `risk_guard.py`, and still does not cover `safeguarding` |
| Every command has a `knos help` page | `pytest tests/test_cli.py -k has_a_help_page` |
| The pull request check can never fail a build | `pytest tests/test_shared_repo.py -k never_returns_non_zero` |
| CI comments on decisions, not only claims | `pytest tests/test_shared_repo.py -k reports_decisions` |
| A full store refuses a claim rather than dropping it | `pytest tests/test_sibyl_is_load_bearing.py -k full_store` |
| `knos status` says how many claims are held | `pytest tests/test_sibyl_is_load_bearing.py -k counts_the_claims` |
| `knos connect` names the exact restart per client | `pytest tests/test_cli.py -k exact_restart` |

Cost: `pip install knos`. No account, no key, no server, no model download,
no network request, and a 5 MB free-tier cap per repo.
