# Install Knos

The Knos command, its MCP server and its Stop hook are one Python package, [`knos` on
PyPI](https://pypi.org/project/knos/). This page lists every way to install them, the check a repository can run on
its pull requests, and the two libraries other projects build on. None of it needs a new account anywhere.

Two parts of the package go into a coding agent:

- **The Stop hook.** When the agent says tests pass, CI is green, it shipped or it is done, Knos runs that check
  itself before the agent may stop. The command is `knos hook proof`.
- **The MCP server.** Tools that only read: `knos_bounties` and `knos_bounty` (paid work on GitHub issues, in test
  USDC on Solana devnet), `knos_check_pr` (is a pull request's "tests pass" true) and `knos_due` (what waits for a
  GitHub account). The command is `knos mcp`. It reads public data from GitHub and Solana and holds no key and no
  wallet.

| For | Do this | It installs |
|---|---|---|
| a terminal | [`pip install knos`](#the-command) | the `knos` command |
| every agent on your machine | [`knos init`](#every-agent-on-the-machine-knos-init) | the hook and the server |
| Claude Code | [two commands](#claude-code) | the hook and the server, as a plugin |
| Codex | [two commands](#codex) | the hook and the server, as a plugin |
| Gemini CLI | [one command](#gemini-cli) | the server, as an extension |
| Cursor | [one link](#cursor) | the server |
| VS Code | [one link](#vs-code) | the server |
| GitHub Copilot coding agent | [one setting and one file](#github-copilot-coding-agent) | the server |
| a repository's pull requests | [a workflow file](#the-github-action) | the free check, as a GitHub Action |
| a JavaScript project | [`npm install <release tarball>`](#the-javascript-client) | the client `knos-settle` |
| a Solana program | [a git dependency](#the-rust-interface-crate) | the crate `knos-oidc-interface` |

The routes for one agent start Knos as `uvx knos ...`, so they need
[uv](https://docs.astral.sh/uv/getting-started/installation/) and nothing else: uv downloads `knos` from PyPI the
first time the agent starts it. uv then keeps running the release it downloaded; `uvx knos@latest --version` moves it
to the newest one.

## The command

```bash
pip install knos        # Python 3.10 or newer; pipx install knos and uv tool install knos work too
uvx knos --version      # or run it without installing anything: uv fetches it
```

It installs the `knos` command. `knos --help` lists what it does.

## Every agent on the machine: `knos init`

```bash
knos init               # undo: knos init --undo
```

It looks for the agents installed on the machine and writes, for each one it finds:

| Agent | Stop hook | MCP server |
|---|---|---|
| Claude Code | `~/.claude/settings.json` | `~/.claude.json` |
| Codex | `~/.codex/hooks.json` (Codex asks you to trust it once) | `~/.codex/config.toml` |
| Cursor | | `~/.cursor/mcp.json` |
| Gemini CLI | | `~/.gemini/settings.json` |

Cursor and Gemini CLI have no hook Knos uses, so they get the server. Nothing else is written. A settings file is
copied to `<file>.knos-backup` before its first change, and `knos init --undo` takes the entries out again.

Run it from an installed `knos`, not as `uvx knos init`: it writes the path of the command it was started from into
each agent's settings, and a path inside uv's cache stops working when the cache is cleaned.

## Claude Code

```bash
claude plugin marketplace add drexthealpha/Knos
claude plugin install knos@knos
```

Inside a session the same two are `/plugin marketplace add drexthealpha/Knos` and `/plugin install knos@knos`.

It installs the plugin `knos` from this repository's [`plugin/`](../plugin) folder: the Stop hook
(`uvx knos hook proof --client claude`) and the MCP server (`uvx knos mcp`). These are the two things `knos init`
writes for Claude Code. Use one of the two routes: with both, the hook runs twice at every stop. To remove it:
`claude plugin uninstall knos@knos`.

## Codex

```bash
codex plugin marketplace add drexthealpha/Knos
codex plugin add knos@knos
```

It installs the same plugin: the MCP server and the Stop hook (`uvx knos hook proof --client codex`). Codex does not
run a plugin's hook until you have reviewed and trusted it. Here too, use the plugin or `knos init`, not both. To
remove it: `codex plugin remove knos@knos`.

For the server alone:

```bash
codex mcp add knos -- uvx knos mcp
```

which writes this to `~/.codex/config.toml`:

```toml
[mcp_servers.knos]
command = "uvx"
args = ["knos", "mcp"]
```

## Gemini CLI

```bash
gemini extensions install https://github.com/drexthealpha/Knos
```

It installs the extension `knos` ([`gemini-extension.json`](../gemini-extension.json)): the MCP server. To remove it:
`gemini extensions uninstall knos`.

## Cursor

[Add Knos to Cursor](https://cursor.com/install-mcp?name=knos&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJrbm9zIiwibWNwIl19)

The link opens Cursor, which asks before it adds the MCP server `knos`. The same link in Cursor's own scheme, to
paste into a browser's address bar:

```text
cursor://anysphere.cursor-deeplink/mcp/install?name=knos&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJrbm9zIiwibWNwIl19
```

Or by hand, in `~/.cursor/mcp.json` (every project) or `.cursor/mcp.json` (one project):

```json
{
  "mcpServers": {
    "knos": { "command": "uvx", "args": ["knos", "mcp"] }
  }
}
```

## VS Code

[Add Knos to VS Code](https://vscode.dev/redirect/mcp/install?name=knos&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22knos%22%2C%22mcp%22%5D%7D)

The link opens VS Code, which shows the MCP server `knos` and asks before it installs it. The same link in VS
Code's own scheme, and a command that adds the server to your user profile from a terminal:

```text
vscode:mcp/install?%7B%22name%22%3A%22knos%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22knos%22%2C%22mcp%22%5D%7D
```

```bash
code --add-mcp "{\"name\":\"knos\",\"command\":\"uvx\",\"args\":[\"knos\",\"mcp\"]}"
```

Or by hand, for one workspace, in `.vscode/mcp.json`:

```json
{
  "servers": {
    "knos": { "command": "uvx", "args": ["knos", "mcp"] }
  }
}
```

## GitHub Copilot coding agent

GitHub now calls it the Copilot cloud agent. There is no file and no link for it: a repository's administrator pastes
the configuration into the repository's settings, under **Settings > Code, planning, and automation > Copilot > MCP
servers**, and saves it.

```json
{
  "mcpServers": {
    "knos": {
      "type": "local",
      "command": "uvx",
      "args": ["knos", "mcp"],
      "tools": ["knos_bounties", "knos_bounty", "knos_check_pr", "knos_due"]
    }
  }
}
```

The agent works on one of GitHub's runners, which has no `uv`. This file, on the default branch, installs it before
the agent starts:

```yaml
# .github/workflows/copilot-setup-steps.yml
name: Copilot Setup Steps
on: workflow_dispatch
jobs:
  copilot-setup-steps:        # GitHub looks for this job name
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0
```

It installs the MCP server for the agent's sessions in that repository.

## The GitHub Action

The free check on every pull request of a repository: when a description says its tests pass or CI is green, Knos
compares that with GitHub's own record of the head commit, and it applies the repository's `CONTRIBUTING.md` rules.
It runs none of the pull request's code, and it involves no bounty, no money and no chain.

```yaml
# .github/workflows/knos.yml
name: knos
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
permissions: {}
jobs:
  knos:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: read
      checks: read
    steps:
      - uses: drexthealpha/Knos@v0.3.12
```

It installs nothing in the repository but this file. The check is the job `knos`: it fails when a claim is false or
a rule is broken, and its summary says which. A branch ruleset can require it. The two read permissions are all it
needs, so it also works on pull requests from forks, and it never needs `pull_request_target`.

Keep it in a workflow file of its own and keep the job's name: Knos does not count the jobs of its own workflow run
as evidence, and it knows its earlier runs on a commit by a name that starts with `knos`. A tag can be moved; to
pin what runs, write the release's full commit sha in place of `v0.3.12`.

To also pay for merged work, a repository uses [`examples/knos-workflow.yml`](../examples/knos-workflow.yml)
instead.

## GitLab CI

For a GitLab merge request that corresponds to a GitHub pull request, set `KNOS_GITHUB_REPOSITORY` to the GitHub
`owner/name` and `KNOS_GITHUB_PR_NUMBER` to that pull request's number in the project's CI/CD variables. `knos check`
reads the pull request and its checks from GitHub; a GitLab merge request with no corresponding GitHub pull request
cannot be checked by this command.

```yaml
# .gitlab-ci.yml
knos:
  image: python:3.12
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
  script:
    - python -m pip install knos
    - printf '{"pull_request":{"number":%s}}' "$KNOS_GITHUB_PR_NUMBER" > .knos-event.json
    - knos check --event .knos-event.json --repo "$KNOS_GITHUB_REPOSITORY"
```

## Get paid: bind a wallet, by hand

A person paid for merged work can name the wallet once, and every later task pays it. Binding is by hand, in two
steps: create a repository from the template [`drexthealpha/knos-claim`](https://github.com/drexthealpha/knos-claim)
(a personal account's, public, named `knos-claim`), then open its Actions tab, choose "knos claim", press "Run
workflow" and paste your address yourself. `knos claim <address>` does both. No link, repository description or
push carries an address in, because an address in a link could be someone else's.

## The JavaScript client

```bash
npm install https://github.com/drexthealpha/Knos/releases/download/v0.3.12/knos-settle-0.3.12.tgz
```

It installs `knos-settle`, the client for Knos's Solana programs: one file with no dependency, for a browser and for
Node 20 or newer ([`sdk/settle`](../sdk/settle)). The tarball is attached to every release.

`knos-settle` is not on npm. A first publish to npm needs the owner to sign in at npmjs.com and create a token, and
nobody else can do that for them. The release workflow publishes the client by itself from the first release after
the repository has that token as the secret `NPM_TOKEN`; until then each release says in one line that it skipped
npm.

## The Rust interface crate

```toml
[dependencies]
knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.12" }
```

It adds `knos-oidc-interface`, the crate a Solana program uses to read a token that knos-oidc verified: no dependency,
no allocation ([`crates/knos-oidc-interface`](../crates/knos-oidc-interface)).

`knos-oidc-interface` is not on crates.io. A first publish to crates.io needs the owner to sign in there and create
a token, and nobody else can do that for them. The release workflow publishes the crate by itself from the first
release after the repository has that token as the secret `CARGO_REGISTRY_TOKEN`; until then each release says in
one line that it skipped crates.io. One consequence: crates.io does not accept a crate that depends on a git
repository, so a crate that uses this one cannot itself be published there yet.

## Any other MCP client

`knos mcp` is a stdio server: the command is `uvx` and its arguments are `knos` and `mcp`. The official MCP registry
lists it as `io.github.drexthealpha/knos`.
