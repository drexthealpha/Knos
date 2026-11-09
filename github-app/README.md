# Knos Gate: the GitHub App

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

Not registered. Registering it is the founder's step: see
[docs/reference/REFEREE.md](../docs/reference/REFEREE.md).

- `app-manifest.json`: the App manifest (permissions: checks write, pull requests write, issues write, actions write,
  contents read, metadata read; events: pull_request, workflow_run, check_run).
- `server.py`: the webhook server. The logic is `knos.gate.app` (tests: `tests/test_gate_app.py`).
- `knos-gate.yml`: the workflow a repository adds for App mode (the App dispatches it; it posts nothing itself).

The App owns the one check run ("Knos Gate") and the one comment. Without the App, the Action alone
(`actions/gate`) gives the same check and comment.
