# Knos in each coding agent

When a coding agent says "done, tests pass", Knos runs that check itself. Where the host lets a hook answer the end
of a turn, a false "done" goes back to the agent with the check that failed, and with what Sibyl remembers of the
claims Knos refused on this repository before. This page says, host by host, what `knos init --host <name>` writes,
whether that host can be made to hold a false "done", which page of the host's own documentation each field was read
from, and how it was tested.

**None of these routes was run inside the real host.** Every one is tested with unit tests on a temporary folder: the
written files are parsed and compared with the fields cited here, and the hook is given an end-of-turn event written
from the host's documentation (`tests/_host_events.py`). Where the documentation does not state a part Knos depends
on, the row says `unconfirmed` and so does the name of every test that uses it. Claude Code and Codex, installed for
the whole machine by plain `knos init`, are in [docs/INSTALL.md](../../docs/INSTALL.md).

```bash
knos init --host cursor            # writes into the current project, and says what it wrote
knos init --host hermes --global   # also the file in your home, for a host that reads nothing from a project
python -m knos.init --host cursor  # the same, without the knos command
```

A second run changes nothing. The home is written only with `--global`. A settings file Knos cannot read is left as
it is. Project files start Knos as `uvx knos` (they are committed and run on other machines); where `uv` is not
installed they name this machine's own `knos`.

## The matrix

All pages were read on 5 October 2026. "Page date" is the date the page itself shows, where it shows one.

| Host (`--host`) | What installs | Can it block a false "done"? | Read from | Tested how |
|---|---|---|---|---|
| Cursor (`cursor`) | MCP: `.cursor/mcp.json`. Hook: `.cursor/hooks.json` (`stop`, and `afterAgentResponse` to keep the message `stop` does not carry). CLI allowlist: `.cursor/cli.json` | **yes**: `{"followup_message": ...}` is sent to the agent as its next message (Cursor stops the loop after 5 by default; Knos lets go after 3) | [hooks](https://cursor.com/docs/agent/hooks), [MCP](https://cursor.com/docs/context/mcp), [CLI permissions](https://cursor.com/docs/cli/reference/permissions); no page date | unit test, recorded event |
| Gemini CLI (`gemini`) | MCP and hook: `.gemini/settings.json` (`mcpServers.knos` with `includeTools`; `hooks.AfterAgent`) | **yes**: `{"decision":"deny","reason":...}` rejects the answer and the reason becomes the next prompt | [hooks reference](https://geminicli.com/docs/hooks/reference/) (page date 10 April 2026), [MCP servers](https://geminicli.com/docs/tools/mcp-server/) (page date 2 September 2026) | unit test, recorded event |
| GitHub Copilot CLI and cloud agent (`copilot`) | Hook: `.github/hooks/knos.json` (`agentStop`). MCP for the cloud agent is a repository setting: the command prints what to paste | **yes**: `{"decision":"block","reason":...}` forces another turn. `unconfirmed`: the event names a transcript and no message, and the transcript's lines are not documented | [hooks configuration](https://docs.github.com/en/copilot/reference/hooks-configuration), [MCP for the cloud agent](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/extend-coding-agent-with-mcp); no page date | unit test, recorded event (`unconfirmed`) |
| VS Code agent mode (`copilot`, or `vscode`) | MCP: `.vscode/mcp.json`. Hook: the same `.github/hooks/knos.json`, which VS Code reads in Copilot's format | **yes**: `hookSpecificOutput` with `decision: "block"`. Hooks are in preview. `unconfirmed`: the transcript's lines, as above, and that Copilot's `agentStop` is run as VS Code's `Stop` (the page says Copilot's format is read and mapped, and does not list the events) | [hooks](https://code.visualstudio.com/docs/copilot/customization/hooks) (page date 30 September 2026), [MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers) | unit test, recorded event (`unconfirmed`) |
| opencode (`opencode`) | MCP: `opencode.json` (`mcp.knos`, and `tools` turning off the three that post). Hook: `.opencode/plugins/knos.js`, a plugin that runs Knos on `session.idle` and prompts the session with the reason | **yes**, through the plugin. `unconfirmed`: the page lists `session.idle` but not its fields, and the plugin has never run in opencode | [plugins](https://opencode.ai/docs/plugins/), [MCP servers](https://opencode.ai/docs/mcp-servers/), [SDK](https://opencode.ai/docs/sdk/); no page date | unit test of the hook's side (`unconfirmed`); the plugin's JavaScript is not run by any test |
| Hermes Agent (`hermes`) | With `--global`, in `~/.hermes/config.yaml`: `mcp_servers.knos` with `tools.include`, and shell hooks `pre_verify` and `pre_llm_call`. Hermes reads nothing from a project: without `--global` the lines are printed | **yes**, on a turn that edited code: `pre_verify` answers `{"action":"continue","message":...}` (Hermes allows 3 in a row). `pre_llm_call` answers `{"context": ...}` with Sibyl's record before the agent speaks | [event hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks), [MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp); no page date | unit test, recorded events |
| goose (`goose`) | Hook: `.agents/plugins/knos/` (`plugin.json`, `hooks/hooks.json` with `Stop`). MCP is in `~/.config/goose/config.yaml` only: the lines are printed | **yes** by its page ("A `Stop` hook that blocks forces the turn to keep going instead of ending"). `unconfirmed`: that the reason reaches the model, and which folder the hook is started in (the event names none) | [hooks](https://goose-docs.ai/docs/guides/context-engineering/hooks/), [extensions](https://goose-docs.ai/docs/getting-started/using-extensions); no page date | unit test, recorded event (`unconfirmed`) |
| aider (`aider`) | `.aider.conf.yml`: `test-cmd` and `auto-test`. No MCP: aider has no MCP client | **each edit**: aider has no hooks and no "done". It runs the test command after each edit and gives the model what it printed when it fails | [linting and testing](https://aider.chat/docs/usage/lint-test.html), [YAML config](https://aider.chat/docs/config/aider_conf.html); no page date | unit test (no event to record) |
| Windsurf, now Devin Desktop (`windsurf`) | Hook: `.windsurf/hooks.json` (`post_cascade_response`, `show_output`). MCP is in the home only: the lines are printed | **annotate only**: only its pre-hooks can block, and nothing a post hook prints goes to the agent. The person sees which check failed. `unconfirmed`: the folder the hook is started in | [Cascade hooks](https://docs.devin.ai/desktop/cascade/hooks), [MCP](https://docs.devin.ai/desktop/cascade/mcp); no page date | unit test, recorded event (`unconfirmed`) |
| Cline (`cline`) | Rule: `.clinerules/knos.md`. MCP with `--global`: `~/.cline/mcp.json` (`autoApprove`) | **no**: its hooks are now plugins for its SDK and CLI ("not applicable on VSCode and JetBrains Extension for now"), and the page does not say a plugin can hold a finished turn. The nearest thing is the rule, which asks | [hooks](https://docs.cline.bot/customization/hooks), [plugins](https://docs.cline.bot/customization/plugins), [MCP](https://docs.cline.bot/mcp/mcp-overview); no page date | unit test of the files |
| Roo Code (`roo`) | MCP: `.roo/mcp.json` (`alwaysAllow`) | **no**: it has no hooks. Its makers ended the product on 15 May 2026; the route is for installs still in use | [MCP in Roo](https://roocodeinc.github.io/Roo-Code/features/mcp/using-mcp-in-roo/) (page date 15 May 2026) | unit test of the file |

Where the answer is "no" or "annotate only", the check that cannot be skipped is the one on the pull request: the
[GitHub Action](../../docs/INSTALL.md#the-github-action) refuses a description that says "tests pass" over a failed
check, whatever the agent was running in.

## The MCP server, and which tools run unasked

`knos mcp` has eleven tools that only read and three that post as the agent's account (`knos_take_work`,
`knos_submit_work`, `knos_collect`). Every route allows only the reading ones, in the field the host has for it:

| Host | Field | What it means there |
|---|---|---|
| Cursor | `permissions.allow`: `Mcp(knos:<tool>)` in `.cursor/cli.json` | the Cursor CLI runs these without asking. `mcp.json` has no such field: the editor asks unless you allow a tool in its settings |
| Gemini CLI | `includeTools` | only these tools exist for the agent |
| Copilot cloud agent | `tools` | only these exist, and they run without asking |
| VS Code | none in `.vscode/mcp.json` | VS Code asks before each tool |
| opencode | `tools`: `knos_<tool>: false` for the three that post | those three are off |
| Hermes Agent | `tools.include` | only these tools exist for the agent |
| Cline | `autoApprove` | these run without asking; the rest ask |
| Roo Code | `alwaysAllow` | these run without asking; the rest ask |
| Windsurf | `disabledTools` (printed, for the file in the home) | the three that post are off |
| goose | none documented | goose asks as its permission mode says |

## One hook, each host's words

`knos hook proof --client <host>` (`src/knos/proof/hook.py`) reads the host's event on stdin and prints the host's
answer. It exits 0 for every host but aider, whose only signal is the exit code.

| Host | Event, and the fields Knos reads | "Not done yet", as the host reads it |
|---|---|---|
| `cursor` | `afterAgentResponse`: `text`, `conversation_id` (kept); then `stop`: `status`, `conversation_id`, `workspace_roots` | `{"followup_message": "..."}` |
| `gemini` | `AfterAgent`: `cwd`, `session_id`, `prompt_response` | `{"decision": "deny", "reason": "..."}` |
| `copilot` | `agentStop`: `cwd`, `sessionId`, `transcriptPath`, `stopReason` | `{"decision": "block", "reason": "..."}` |
| `copilot` in VS Code | `Stop`: `cwd`, `sessionId`, `transcript_path`, `hookEventName` | `{"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": "..."}}` |
| `hermes` | `pre_verify`: `cwd`, `session_id`, `extra.final_response` | `{"action": "continue", "message": "..."}` |
| `hermes` | `pre_llm_call`: `cwd` (no check is run) | `{"context": "<what Sibyl remembers>"}`, or nothing |
| `goose` | `Stop`: `session_id`, `last_assistant_message` | `{"decision": "block", "reason": "..."}` |
| `opencode` | what the plugin sends: `cwd`, `session_id`, `last_assistant_message` | `{"decision": "block", "reason": "..."}`, which the plugin sends as a prompt |
| `windsurf` | `post_cascade_response`: `trajectory_id`, `tool_info.response` | the text, shown to the person |
| `aider` | none | the text, and exit code 1 |

A stop a person interrupted (`status` other than `completed` in Cursor, `stopReason: user_interrupt` in Copilot) is
not judged. After three blocks on the same evidence Knos lets the agent stop and says what is unproven, in every
host, so a check the agent cannot fix never traps it.

## Sibyl in every route

What Knos refused on a repository is kept in Sibyl's memory engine (`sibyl-memory-client`, in `~/.sibyl-memory/`), and
nowhere else. The hook reads it on every stop, whatever the host: a check that failed last time is run again even
when the new message does not mention it, and the answer the host carries back says what failed last time and how
many claims were refused here. `tests/test_sibyl_is_load_bearing.py` and `tests/test_sibyl_tamper.py` send each
host's event through the hook and show the answer disappear when the store is deleted, when no Sibyl is there, and
when its journal or a rule is edited by hand.

Sibyl's releases were read from PyPI on 5 October 2026 and again on 6 October 2026 (`https://pypi.org/pypi/<package>/json`),
with the same result:

| Package | Latest | Used by Knos |
|---|---|---|
| `sibyl-memory-client` | 0.8.1 (7 September 2026) | yes: the dependency, `>=0.8.1`. Nothing newer exists |
| `sibyl-memory-mcp` | 0.2.1 (7 September 2026) | no. Its eight tools (`memory_remember`, `memory_recall`, `memory_search`, `memory_list`, `memory_forget`, `memory_set_state`, `memory_get_state`, `memory_record_event`) have the same names and arguments as in 0.1.13 (7 August 2026); since then it requires `sibyl-memory-client>=0.8.1` and `sibyl-memory-hermes>=0.4.0`, and takes its vocabulary of search verdicts from the client |
| `sibyl-memory-hermes` | 0.4.1 (7 September 2026) | no. It makes Sibyl the memory provider of Hermes Agent: `pip install sibyl-memory-hermes`, `sibyl-memory-hermes install-plugin`, then `memory.provider: sibyl` in `~/.hermes/config.yaml` |

Hermes Agent with that provider and Knos keep their memories in the same Sibyl store file by default
(`~/.sibyl-memory/memory.db`). Knos keeps each repository under a tenant of its own, so its record is not among what
Hermes recalls by itself: the `pre_llm_call` hook is what tells Hermes's agent about it.

Three facts about the engine that bound what Knos can promise, each from the packages' own pages on PyPI and
[docs.sibyllabs.org/memory](https://docs.sibyllabs.org/memory/), read 6 October 2026:

- The engine's pages say it runs on Linux, macOS and Windows through WSL2, and that "Native Windows is not supported".
  Knos's test workflow has Windows jobs that use the store (`.github/workflows/tests.yml`); that is Knos's own
  testing, not the engine's promise.
- An account on the free plan has a 5 MB local cap; a write past it is refused. `MemoryClient.free_tier_status()`
  reports how full the store is. The paid plan, Pro, removes the cap and adds self-learning and the memory linter
  ([plans](https://docs.sibyllabs.org/memory/tiers)). Knos needs neither: `learn()` is tried and never required.
- Search is lexical (SQLite FTS5), with no embedding model. The engine stores entities by category and name, state,
  a journal and reference documents. It has no typed relations between entities: Knos expresses "this supplier,
  under these terms" through the category and the name it chooses, and that stays true of the list below.

### Next uses

What `sibyl-memory-client` 0.8.1 offers that Knos does not call yet, each with the use it would have here. None is
built. Every one would go through [`knos.proof.history`](../../src/knos/proof/history.py), as everything Knos
remembers does.

| The engine offers | Knos uses today | The use |
|---|---|---|
| `read_events(since=, until=)`: the journal between two times | `read_events(limit=)` only | "What was refused under these terms last quarter": a supplier's record over a statement's period, and a buyer's refusals between two closings |
| `search(..., tiers=)` and `prefix=`: search held to chosen tiers, and by word prefix | `search(query, limit)` across all tiers | A reviewer's memory of disputes: search the journal alone for an appeal's words without an entity's body answering for it; find `tests/conftest` by its prefix |
| The verdict on every result (`SearchResults.verdict`: `ok`, `no_match`, `empty_store`, `gated` and others) | the hits only | Preflight could tell "nothing like this was refused here" from "this store is empty" in the engine's own words |
| The REFERENCE tier (`set_reference`, `get_reference`): a named document | not used | The terms of a standing offer and a rate card, kept whole under their hash, so "what was refused under these terms" recalls the terms and not only their hash |
| `archive_entity`: out of the active set, still on disk | `set_entity`, `list_entities`, `search_entities(category=)` | A rule a successful appeal overturned is archived with the reason, so it stops deciding and its history stays |
| Tenants (`set_tenant`, one store, isolated identities) | one tenant per repository; `knos-judge` for a judge's run | A supplier's delivery record across buyers: one tenant the supplier owns, written from each buyer's statement the supplier acknowledged, read by preflight under `--by` |
| `free_tier_status()` | not used | `knos preflight` and the Stop hook say when the store is near its cap, before a write is refused |
| `sibyl-memory-mcp` 0.2.1: the store as eight MCP tools | not used | An agent host that already runs Sibyl's server could be pointed at a repository's tenant (the server's Docker instructions pass `SIBYL_TENANT_ID` through) and read Knos's record with no second server. Its tools can also write, so who may write a repository's record has to be decided first |

## What is not done

- No route was run in its host. The first run in each will show whether the `unconfirmed` parts hold.
- `knos init --undo` does not remove what `--host` wrote: delete the files it listed, or the `knos` entries in them.
- The opencode plugin is JavaScript that no test runs.
- Cline's editor extension, Roo Code and Windsurf cannot be made to hold a false "done" with what they document today.
