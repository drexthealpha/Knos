# `knos mcp`: tools, resources, prompts and a confirmation before each post

`knos mcp` speaks the Model Context Protocol on stdio: the stateless 2026-07-28 version (`server/discover`) and the
session versions before it ([specification](https://modelcontextprotocol.io/specification/2026-07-28), read 14 Oct
2026). Its tools are listed in `src/knos/mcp.py`. Since 0.4.0 it also serves (`src/knos/mcp_more.py`):

**Resources** (`resources/list`, `resources/read`), each a JSON document:

| uri | what |
| --- | --- |
| `knos://fees` | every Knos fee from `config/fees.yaml`, with each line's status; on devnet all money is test money |
| `knos://cheats` | the rules Knos refuses work by: read them before writing the change |

**Resource templates** (`resources/templates/list`):

| uri template | what |
| --- | --- |
| `knos://bounty/{owner}/{repo}/{issue}` | the money held on one issue (the same answer as the `knos_bounty` tool) |
| `knos://due/{login}` | what waits and what was paid for a GitHub account (`knos_due`) |
| `knos://token/{address}` | whether a mint's tokens can be held, or an account receive a payout ([PLATFORM.md](PLATFORM.md)) |

`KNOS_MCP_REPOS` limits the bounty template to its repositories, as it limits the tools.

**Prompts** (`prompts/list`, `prompts/get`):

| prompt | what |
| --- | --- |
| `earn_a_bounty` | find, reserve, verify, submit, collect |
| `fund_a_bounty` | `issue`, `amount`: the fee and terms first, nothing posted until the person says yes |
| `before_pull_request` | run `knos_verify`, paste its lines |

**Output schema**: every tool declares `outputSchema: {"type": "object"}`; every answer is one JSON object in
`structuredContent`, with the same JSON as text beside it.

## Two official extensions: tasks and skills

To a client that sends its own extension capabilities in `_meta`, `server/discover` also lists two extensions of the
current revision (a client that names none gets the core capabilities, as before) ([extensions](https://modelcontextprotocol.io/extensions/overview),
read 14 Oct 2026; `src/knos/mcp_ext.py`):

- **Tasks** (`io.modelcontextprotocol/tasks`, schema in
  [ext-tasks](https://github.com/modelcontextprotocol/ext-tasks) `schema/2026-07-28`). A referee re-run takes
  minutes. A client that declares the extension in the request's
  `_meta["io.modelcontextprotocol/clientCapabilities"].extensions` and calls `knos_verify` gets a `CreateTaskResult`
  at once (`resultType: "task"`, `taskId`, `status: "working"`, `createdAt`, `lastUpdatedAt`, `ttlMs`,
  `pollIntervalMs`) and polls `tasks/get` until `completed` (with `result`, what the call would have answered),
  `failed` (with `error`) or `cancelled`; `tasks/cancel` and `tasks/update` are answered. A client that did not
  declare it gets the answer itself, as before. Tasks live in the server's memory: a restarted server forgets them.
- **Skills** (`io.modelcontextprotocol/skills`, SEP-2640). `skills/list` and `skills/get` list the Knos skills the
  plugin ships (`plugin/skills/*`, packaged as `knos/_skills`), each file with its sha256 and size;
  `resources/read` serves `skill://<name>/<file>`, only files of a listed skill.

## A person confirms each post

The tools that post to GitHub as the person's account (`knos_take_work`, `knos_submit_work`) are off until the
operator turns them on (`KNOS_AGENT_ACT=1`). When they are on and the client declared that it can ask its user
(`elicitation`, form mode, in the request's client capabilities), the tool does not post at once.

It answers `resultType: "input_required"` with one `elicitation/create` request showing the exact method, path and
body it would send. The client shows it, and calls again with the answer and the `requestState` it was given.

Only an `accept` with `post: true` sends, and only those bytes: the state is sealed with a key held by the running
server, the seal names whether a request was shown or approved, and it lapses after 10 minutes. A decline, a cancel, a
state the server did not seal, or a changed request sends nothing.

An unattended agent on an `auto` order sets `KNOS_AGENT_CONFIRM=0`; a client that cannot ask is not asked.

This uses multi-round-trip requests, which are in the 2026-07-28 version only; a session client (2025 versions) is
served as before.
