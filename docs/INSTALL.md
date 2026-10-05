# Install Knos

The Knos command, its MCP server and its Stop hook are one Python package, [`knos` on
PyPI](https://pypi.org/project/knos/). This page lists every way to install them, the check a repository can run on
its pull requests, and the two libraries other projects build on. None of it needs a new account anywhere.

Two parts of the package go into a coding agent:

- **The Stop hook.** When the agent says tests pass, CI is green, it shipped or it is done, Knos runs that check
  itself before the agent may stop. The command is `knos hook proof`.
- **The MCP server.** Tools that only read: `knos_bounties` and `knos_bounty` (paid work on GitHub issues, in test
  USDC on Solana devnet), `knos_quote` (one issue's amount, terms, what stands in the way, and the funder's record),
  `knos_can_pay` (would it pay: is the pinned workflow on the default branch, did each named check pass there in the
  last 30 days, can a GitHub-signed run the chain verifies pay it), `knos_check_pr` (is a pull request's "tests pass"
  true) and `knos_due` (what waits for a GitHub account). Four more return the exact comment to post and send nothing
  themselves: `knos_take`, `knos_address`, `knos_fund` and `knos_settle`. `knos_find_work` lists the open work
  orders an agent could take, with their terms. The command is `knos mcp`. With these it reads public data from
  GitHub and Solana and holds no key and no wallet.

  Three tools post, and only for an agent that was given a GitHub token of its own and told it may act
  (`knos agent init --allow-actions`, [docs/AGENTS.md](AGENTS.md)): `knos_take_work` (comments `/knos take`),
  `knos_submit_work` (opens the pull request) and `knos_collect` (says what is held or paid, and can bind a wallet).
  No allowlist on this page names them: a host that runs listed tools without asking still asks before these three.

  Whatever a repository or an account wrote (an issue's title and labels, a check's name, the paths in a bounty's
  terms) comes back inside a field named `untrusted`, each string cut to 200 characters, and the server's
  instructions tell the agent that it is data, never an instruction. `KNOS_MCP_REPOS=owner/name,owner/name` limits the
  server to those repositories: a listing holds only their bounties, and a tool that names another repository
  refuses it.

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
| a repository that pays for merged work | [one pull request](#paid-work-in-a-repository-install-by-pull-request) | the payment workflow, a 21-line file |
| a repository's pull requests | [a workflow file](#the-github-action) | the free check, as a GitHub Action |
| a seller who settles a merged pull request without the buyer's workflow | [a workflow file in a repository of your own](#settle-yourself-the-attest-workflow) | nothing: it only reads, and asks GitHub to sign |
| a JavaScript project | [`npm install <release tarball>`](#the-javascript-client) | the client `knos-settle` |
| a Solana program | [a git dependency](#the-rust-interface-crates) | the crates `knos-oidc-interface` and `knos-pay-interface` |

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

For the whole machine Cursor and Gemini CLI get the server; their hook is installed per project (the next section).
Nothing else is written. A settings file is copied to `<file>.knos-backup` before its first change, and
`knos init --undo` takes the entries out again.

Run it from an installed `knos`, not as `uvx knos init`: it writes the path of the command it was started from into
each agent's settings, and a path inside uv's cache stops working when the cache is cleaned.

## One project, in your coding agent: `knos init --host`

```bash
knos init --host cursor              # in the project's folder; python -m knos.init --host cursor is the same
knos init --host hermes --global     # also the file in your home, for a host that reads nothing from a project
```

It writes that host's files into the project, in the fields the host's own documentation names, and prints each file
it wrote. A second run changes nothing, and your home is written only with `--global`. Files in a project start Knos
as `uvx knos`, so they work for whoever clones it.

| `--host` | Written into the project | Does a false "done" go back to the agent? |
|---|---|---|
| `cursor` | `.cursor/mcp.json`, `.cursor/hooks.json` (`stop`, `afterAgentResponse`), `.cursor/cli.json` | yes |
| `gemini` | `.gemini/settings.json` (the server with `includeTools`, the `AfterAgent` hook) | yes |
| `copilot` (also `vscode`) | `.github/hooks/knos.json` (`agentStop`; Copilot CLI, the cloud agent and VS Code read it), `.vscode/mcp.json` | yes |
| `opencode` | `opencode.json`, `.opencode/plugins/knos.js` | yes, through the plugin |
| `hermes` | nothing: Hermes Agent reads `~/.hermes/config.yaml` only. `--global` adds the server and the `pre_verify` and `pre_llm_call` hooks there | yes, on a turn that edited code |
| `goose` | `.agents/plugins/knos/` (a `Stop` hook) | yes, by goose's documentation |
| `aider` | `.aider.conf.yml` (`test-cmd`, `auto-test`) | aider has no hooks: it runs Knos after each edit and gives the model what failed |
| `windsurf` | `.windsurf/hooks.json` (`post_cascade_response`) | no: the person is shown which check failed; a post hook there cannot hold a turn |
| `cline` | `.clinerules/knos.md`; with `--global`, `~/.cline/mcp.json` | no: there is no hook for it in the editor extension; the rule asks |
| `roo` | `.roo/mcp.json` | no: Roo Code has no hooks |

The MCP server is written with only the tools that read allowed to run unasked (or offered at all, where that is the
host's only switch); the three that post as the agent's account are asked about each time.

Each field was read from the host's documentation on 5 October 2026, and each route is tested on a temporary folder
with an end-of-turn event written from that documentation. None was run inside the real host. Where the
documentation does not state something Knos depends on (Copilot's and VS Code's transcript lines, the fields of
opencode's `session.idle`, the folder goose and Windsurf start a hook in), the route is marked `unconfirmed`. The
pages, the dates they show, the exact event and answer for each host, and what Sibyl's memory adds to the answer are
in [integrations/hosts/README.md](../integrations/hosts/README.md):

| Host | Pages read (5 October 2026) |
|---|---|
| Cursor | [hooks](https://cursor.com/docs/agent/hooks), [MCP](https://cursor.com/docs/context/mcp), [CLI permissions](https://cursor.com/docs/cli/reference/permissions) |
| Gemini CLI | [hooks reference](https://geminicli.com/docs/hooks/reference/) (dated 10 April 2026), [MCP servers](https://geminicli.com/docs/tools/mcp-server/) (dated 2 September 2026) |
| GitHub Copilot | [hooks configuration](https://docs.github.com/en/copilot/reference/hooks-configuration), [MCP for the cloud agent](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp) |
| VS Code | [hooks](https://code.visualstudio.com/docs/copilot/customization/hooks) (dated 30 September 2026; in preview), [MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers) |
| opencode | [plugins](https://opencode.ai/docs/plugins/), [MCP servers](https://opencode.ai/docs/mcp-servers/) |
| Hermes Agent | [event hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks), [MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) |
| goose | [hooks](https://goose-docs.ai/docs/guides/context-engineering/hooks/), [extensions](https://goose-docs.ai/docs/getting-started/using-extensions) |
| aider | [linting and testing](https://aider.chat/docs/usage/lint-test.html), [YAML config](https://aider.chat/docs/config/aider_conf.html) |
| Windsurf (now Devin Desktop) | [Cascade hooks](https://docs.devin.ai/desktop/cascade/hooks), [MCP](https://docs.devin.ai/desktop/cascade/mcp) |
| Cline | [hooks](https://docs.cline.bot/customization/hooks), [plugins](https://docs.cline.bot/customization/plugins), [MCP](https://docs.cline.bot/mcp/mcp-overview) |
| Roo Code | [MCP](https://roocodeinc.github.io/Roo-Code/features/mcp/using-mcp-in-roo/) (dated 15 May 2026, the day its makers ended the product) |

What `--host` wrote is not removed by `knos init --undo`: delete the files it listed, or the `knos` entries in them.

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
      "tools": ["knos_bounties", "knos_bounty", "knos_check_pr", "knos_due", "knos_quote", "knos_can_pay", "knos_take", "knos_address", "knos_fund", "knos_settle", "knos_find_work"]
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

## Paid work in a repository: install by pull request

On Solana devnet, with test USDC, a repository goes from nothing to a funded issue in three steps. Counted honestly,
each step is one thing you do on github.com, with your GitHub account and nothing else: no app to install, no
wallet, no secret, no other account.

1. **Open the install link and commit.** `knos init --pr owner/repo` prints the link (add `@branch` when the default
   branch is not `main`); the site builds the same one from a text box. It is GitHub's own "new file" page with
   `.github/workflows/knos.yml` filled in: `https://github.com/<owner>/<repo>/new/<branch>?filename=...&value=...`.
   Press "Commit changes" and choose "Create a new branch for this commit and start a pull request" (without write
   access GitHub forks the repository and the button says "Propose new file"). Nothing is sent by the command or by
   the site: the link is the whole install. With the GitHub CLI (`gh`) on your machine, `knos init --pr` also opens the
   pull request itself, on a branch `knos-install`, and says so; when it cannot, it changes nothing and leaves the link.
2. **Merge that pull request.** GitHub runs `issue_comment` and `issues` workflows from the default branch only, so
   nothing happens before the merge.
3. **Comment `/knos fund 20` on an issue.** On devnet the program's faucet gives the test USDC (at most 100 per
   comment, once per repository per minute), so the comment is all it takes. The reply states the terms. `knos terms
   list` has five ready comments (below).

What follows is the work, not the install: someone opens a pull request that says `Fixes #<issue>`, comments
`/knos address <their Solana address>` on it, and is paid when it is merged with the terms met. Without an address
the money waits for them (180 days at most).

The file is [`examples/knos-install.yml`](../examples/knos-install.yml), 21 lines, one of them a comment. It has the triggers of the long
form, [`examples/knos-workflow.yml`](../examples/knos-workflow.yml), and calls the same two workflows of
drexthealpha/knos-workflows at the same full commit. The program takes a token by the workflow that produced it
(`job_workflow_ref`, `job_workflow_sha`: the called workflow's file and commit), not by the file that called it, so a
short caller in your repository is paid exactly as the long one is. Three differences, none hidden:

- One job calls `prove.yml` where the long form has two (settle and review). `prove.yml`'s own conditions pick the job, so the same jobs run.
- It does not hand on the optional secret `KNOS_RELAY_KEY`: tokens are posted as comments and Knos's public relay
  carries them. A repository that wants to carry its own uses the long form.
- It has one comment line. The long form's comments say what every trigger does; read them before you merge.

It is short because the link must carry it: GitHub refuses an address over 8,191 bytes
([github/docs#5136](https://github.com/github/docs/issues/5136)). The link is 2,573 bytes for a repository named
`acme/widgets` (measured: `len(knos.init.install_link("acme/widgets", <the file>))`). The link uses only the two
query parameters GitHub's editor is known to read, `filename` and `value`; the commit message and the pull request's
title are GitHub's defaults.

**A private repository** runs no Knos file. One repository of the organisation is its attestor and funds and pays
for the others; the site gives a second link, for [`examples/knos-attestor.yml`](../examples/knos-attestor.yml)
without its comment lines (with them it does not fit in a link). That is more than three steps: the attestor also
needs `.knos/policy.yml` (`private: true`, `attestor:`, `targets:`) and a secret `KNOS_READ_TOKEN`, a fine-grained
token that reads the repositories it attests for.

### What `knos.yml` does, and what it cannot

What it does:

- Answers every comment with a line that starts with `/knos`, on issues and on pull requests. `/knos help` lists the
  commands.
- On `/knos fund` (or a new issue whose description has that line), asks GitHub to sign a statement for one action:
  fund this task from this Balance. Anyone may carry a statement to Solana; it does only what it names, once.
- On a push to the default branch, for each merged pull request that closes a funded issue: reads GitHub's record of
  the merged commit against the task's funded terms, and only when every funded check passed and the changed files
  are in scope asks GitHub to sign the statement that pays.
- Comments on issues and pull requests, and assigns an issue for `/knos take`.
- Can be started by hand (Actions, then knos, then Run workflow, with a merged pull request's number) to try a
  payment again.

What it cannot do:

- Hold or move money. It has no wallet and no bounty's money. Money moves only on Solana, after the program has
  checked GitHub's signature, and only as the statement and the task's terms say.
- Change your code, branches or settings: it can read, comment and assign, and nothing else.
- Spend a Balance past what its wallet allowed: only comments by the Balance's owner and the people it lists count,
  and no task takes more than its cap.
- Change a task's terms after funding, or take a payment back once it has been attested.
- Be changed by a pull request: it runs from the default branch, it does not use `pull_request_target`, and a pull
  request that edits `.github/` or `.knos/` is out of a task's scope.
- Vouch for more than its repository can: GitHub signs which workflow ran, at which commit, in which repository, not
  what it read there. So a task's checks are judged in the funder's own repository, about the funder's own money.

No secret is needed. The signed statements are posted as comments, and Knos's public relay carries them to Solana and
pays the fees. Optional: a repository secret `KNOS_RELAY_KEY`, a Solana key with a little SOL for fees and never a
bounty's money, lets the jobs carry their own statements instead of waiting for the relay.

### The optional second file, `knos-check.yml`

`knos-check.yml` checks every pull request, forks included, and moves no money. It reads, and it reports through its
own status (`check / claims`) and the job's summary. A first-time contributor's first run waits for a maintainer's
approval on the pull request's page. GitHub runs it as the pull request has it, so a pull request can change it for
its own run: that is why it is advice, and nothing about money depends on it. With the first file alone everything
about money works; `/knos status` on a pull request then tells its author what the check would have said.

### Terms from a template

```bash
knos terms list                 # the five, one sentence each
knos terms show bugfix          # the comment to post, the terms JSON the program hashes, its sha256
```

| Template | The comment | What it says |
|---|---|---|
| `bugfix` | `/knos fund 50 checks: unit, lint paths: src/**, tests/**` | named checks must pass; only `src/` and `tests/` may change |
| `feature-blackbox` | `/knos fund 80 checks: unit` on an issue with `.knos/acceptance/<issue>/` | paid when the black-box acceptance suite passes |
| `milestone` | `/knos fund 100 checks: unit holdback 20 warranty 30 days 30` | 20% waits 30 days |
| `standing-rate` | `/knos offer @octocat rate 10 budget 100 checks: unit days 90` | one vendor, a rate per accepted pull request, up to a budget |
| `private-attested` | `/knos fund 50 checks: unit paths: src/**` on an issue of a private repository | funded and paid by the attestor repository |

Each is a file in [`examples/terms/`](../examples/terms): the comment, one sentence written from its fields, the
exact terms JSON and its hash. A test reads every comment with the parser that reads real comments and builds its
terms with the code that fixes a real bounty's, and holds the hash equal to the file's. The JSON is made with sample
facts a template cannot know (the id of the GitHub App behind each check, your acceptance bundle's hash, your
policy's hash, your vendor's account id); each file says which. The reply to your own comment shows your
repository's terms.

### What a funder with real money would additionally need

Knos runs on Solana devnet only. There is no mainnet deployment, so nobody can do the following with real money
today; this is the list of what it would take, so that no step is hidden. The devnet faucet stands in for all of it.

4. **A wallet.** A Solana wallet app, or the passkey wallet the site makes (no app, no seed phrase).
5. **USDC in it**, bought or sent from an exchange. With a wallet app, also a little SOL for transaction fees. With
   the passkey wallet a relayer pays the transaction fee (knos_passkey 1.1, `Fund`).
6. **A Balance.** The wallet opens one for a GitHub owner (a person or an organisation) and puts USDC in: one or two
   signatures on the site. This is where a `/knos fund` comment takes its money from.
7. **Its limits**, in the same place: a cap per order, limits per day and in total, the repositories that may spend
   it, and up to four other GitHub accounts that may spend it by comment. Optional, and worth doing before the first
   comment.

So: three steps on devnet, seven with real money. The fee is paid by the funder on top of the amount (2.5% of the
first 1,000, 1% from 1,000 to 50,000, 0.5% above; minimum 0.40).

## The GitHub Action

The free check on every pull request of a repository: when a description says its tests pass or CI is green, Knos
compares that with GitHub's own record of the head commit, and it applies the repository's `CONTRIBUTING.md` rules.
A ticked box of a template's checklist (`- [x] My PR passes all CI/CD checks`) is the author's claim; an unticked
box, the template's HTML comments and a sentence that hedges or instructs ("tests should pass", "make sure CI is
green") are not.
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
      - uses: drexthealpha/Knos@v0.3.16
```

It installs nothing in the repository but this file. The check is the job `knos`: it fails when a claim is false or
a rule is broken, and its summary says which. A branch ruleset can require it. The two read permissions are all it
needs, so it also works on pull requests from forks, and it never needs `pull_request_target`.

Keep it in a workflow file of its own and keep the job's name: Knos does not count the jobs of its own workflow run
as evidence, and it knows its earlier runs on a commit by a name that starts with `knos`. A tag can be moved; to
pin what runs, write the release's full commit sha in place of the tag after `@`.

To also pay for merged work, a repository uses [`examples/knos-workflow.yml`](../examples/knos-workflow.yml)
instead.

## GitLab CI

A GitLab project that runs CI/CD for a GitHub repository (GitLab's "CI/CD for external repositories") runs a
pipeline for each GitHub pull request, and hands that pipeline the pull request's number as
`CI_EXTERNAL_PULL_REQUEST_IID`. Set `KNOS_GITHUB_REPOSITORY` to the GitHub `owner/name` in the project's CI/CD
variables; the number comes with each pipeline, so each pull request is checked as itself. `knos check owner/name#N` reads
that pull request from GitHub, its description and the checks GitHub recorded at its head commit, and the job fails
when the description says tests pass or CI is green and a check failed there. It also fails when GitHub cannot be
read, rather than pass on a pull request it did not see. A masked `GH_TOKEN` variable, a token that can read the
repository, lifts GitHub's limit on anonymous reads, which a shared runner's address may have used up. A GitLab merge
request with no GitHub pull request behind it cannot be checked by this command.

```yaml
# .gitlab-ci.yml
knos:
  image: python:3.12
  rules:
    - if: '$CI_PIPELINE_SOURCE == "external_pull_request_event"'
  script:
    - python -m pip install knos==0.3.16
    - knos check "$KNOS_GITHUB_REPOSITORY#$CI_EXTERNAL_PULL_REQUEST_IID"
```

## Get paid: bind a wallet, by hand

A person paid for merged work can name the wallet once, and every later task pays it. Binding is by hand, in two
steps: create a repository from the template [`drexthealpha/knos-claim`](https://github.com/drexthealpha/knos-claim)
(a personal account's, public, named `knos-claim`), then open its Actions tab, choose "knos claim", press "Run
workflow" and paste your address yourself. `knos claim <address>` does both. No link, repository description or
push carries an address in, because an address in a link could be someone else's.

An organisation binds a wallet the same way, from a repository named `knos-claim` that the organisation owns: a
member starts the claim workflow by hand. That takes effect with `knos-pay` 2.1
([SECURITY.md](SECURITY.md), section 8).

With no wallet app: the site's "Get paid" section makes a passkey on your device and shows the address it derives.
Use that address like any other. Withdrawing needs only the passkey. Read [SECURITY.md](SECURITY.md), section 17,
first: a lost passkey is lost money.

## Settle yourself: the attest workflow

For the person who did the work. Put [`examples/knos-attest.yml`](../examples/knos-attest.yml) in a repository you
own, as `.github/workflows/knos-attest.yml`. It needs no secret and writes nothing. After your pull request is merged
in a public repository, `knos settle --neutral <pull request URL>` starts it by hand through your `gh` login, or you
start it from the Actions tab. It reads GitHub's public record of the pull request and the work order on Solana,
and asks GitHub to sign only what that record supports. The escrow pays on that run when the order allows it, which
is the default; an order funded with `neutral off` does not. This takes effect with `knos-pay` 2.1.

## The JavaScript client

```bash
npm install https://github.com/drexthealpha/Knos/releases/download/v0.3.16/knos-settle-0.3.16.tgz
```

It installs `knos-settle`, the client for Knos's Solana programs: one file with no dependency, for a browser and for
Node 20 or newer ([`sdk/settle`](../sdk/settle)). The tarball is attached to every release.

`knos-settle` is not on npm. A first publish to npm needs the owner to sign in at npmjs.com and create a token, and
nobody else can do that for them. The release workflow publishes the client by itself from the first release after
the repository has that token as the secret `NPM_TOKEN`; until then each release says in one line that it skipped
npm.

## The Rust interface crates

```toml
[dependencies]
knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.16" }
```

It adds `knos-oidc-interface`, the crate a Solana program uses to read a token that knos-oidc verified: no dependency,
no allocation ([`crates/knos-oidc-interface`](../crates/knos-oidc-interface)). It reads the second deployment unless
a program names the first (`v1::read`).

[`crates/knos-pay-interface`](../crates/knos-pay-interface) is the second crate, added the same way from the same
repository: the addresses and instructions a program needs to fund, top up and refund a work order from an account
it controls. [COMPOSE.md](COMPOSE.md) lists the examples built on both.

`knos-oidc-interface` is not on crates.io. A first publish to crates.io needs the owner to sign in there and create
a token, and nobody else can do that for them. The release workflow publishes the crate by itself from the first
release after the repository has that token as the secret `CARGO_REGISTRY_TOKEN`; until then each release says in
one line that it skipped crates.io. One consequence: crates.io does not accept a crate that depends on a git
repository, so a crate that uses this one cannot itself be published there yet.

## Any other MCP client

`knos mcp` is a stdio server: the command is `uvx` and its arguments are `knos` and `mcp`. The official MCP registry
lists it as `io.github.drexthealpha/knos`.
