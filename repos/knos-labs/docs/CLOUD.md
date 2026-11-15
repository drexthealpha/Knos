# Knos in cloud sandboxes

A cloud agent obeys the same claims as the laptops: it needs `pip install knos`, a member key, and outbound access to
one Solana RPC host. No server is involved.

## 1. Give the sandbox a key

On the team owner's machine:

```
knos team add x --cloud ci-sandbox
```

This makes a **revocable member key** (not a "scoped" one) and writes it owner-only to
`~/.knos/team/cloud-ci-sandbox.json`. Put that file's contents into your vendor's secret settings as
`KNOS_MEMBER_KEY`. Blast radius: the key can create, renew and close claims and write records in this team. It cannot
change the member list or move any budget. Revoke it with `knos team remove <its public key>`.

## 2. Commit the guard with the repo

On any machine in the repo:

```
knos init --team
```

It writes the hooks into `.claude/settings.json` and `.codex/hooks.json`, installs the Knos plugin at project scope,
and adds the git commit guard to this clone. Commit the two files and `.knos/team.json`.

## 3. Per vendor

### Claude Code (cloud sessions)

- Cloud sessions ignore plugins but do run the hooks committed in the repo's `.claude/settings.json`. This works in
  single-repo sessions, not in Projects threads.
- The default network allows package registries only. In the environment's network settings choose **Custom** and
  allow your RPC host (for devnet, `api.devnet.solana.com`).
- Setup script: `pip install knos`. Add `KNOS_MEMBER_KEY` as an environment secret.

### GitHub Copilot cloud agent

- Copy `.github/hooks/knos.json.example` to `.github/hooks/knos.json`. Copilot's `preToolUse` hooks deny on exit 2.
  Any other non-zero exit also denies, so the template exits 0 when `knos` is missing.
- Add `pip install knos` to `.github/workflows/copilot-setup-steps.yml`.
- Add your RPC host to the agent's firewall allowlist, and `KNOS_MEMBER_KEY` as a secret of the `copilot`
  environment.

### Codex cloud

- Setup script: `pip install knos`.
- Add the RPC host to the environment's domain allowlist, and `KNOS_MEMBER_KEY` as a secret.
- `.codex/hooks.json` in the repo loads once the project is trusted.

## If the RPC is blocked

Edits go ahead in local-only mode with a one-line warning: Knos never blocks work because an RPC is down. The other
members see this sandbox's claims lapse at their lease.

## Tested

`tests/test_team_two_homes.py` runs a simulated cloud sandbox: a fresh shallow clone and a fresh home, with the
member key only in `KNOS_MEMBER_KEY`. Its edit to a file another machine claimed is refused, on a local validator
running the devnet-deployed programs. No real vendor-cloud run is part of the test suite.
