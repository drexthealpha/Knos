# Integrating with Knos

Several ways in. `knos init` wires the first two for Claude Code, Codex, Cursor, OpenCode and Claude Desktop.

## 1. The MCP server (any host that speaks MCP)

Start it over stdio with `knos mcp`. The config entry `knos init` writes:

```json
{"mcpServers": {"knos": {"command": "/absolute/path/to/knos", "args": ["mcp"]}}}
```

It answers only for the repo the host starts it in, and says so plainly outside a git repo.

| tool | arguments | what it does |
|---|---|---|
| `search` | `query`, `limit=8` | answers from past sessions (Claude Code, Codex, Cursor), commits, CLAUDE.md / AGENTS.md and code structure, each with its source; lines starting `[claimed]` say who holds files the answer touches |
| `about` | `thing` | everything known about one file, person, topic or symbol |
| `remember` | `fact`, `about`, `claiming=false`, `paths=[]` | writes a note every later session sees; with `claiming=true` it also claims `paths` (files, folders, globs like `src/parser/**`) for about 30 minutes, refreshed by claiming again |
| `done` | `about=""` | releases your own claims (one, by description or id, or all of yours); never anyone else's |
| `pay` (Pro) | `url`, `method`, `body`, `agent` | fetches an API; if it answers 402 over MPP or x402, pays it from that agent's own wallet, inside its cap |
| `post_job` | `title`, `task`, `price_usdc`, `kind`, `checks_json`, `work_minutes`, `review_hours` | hires any agent: the price goes into the Solana escrow, paid only on acceptance |
| `find_jobs` | `kind=""` | open jobs this agent could take and be paid for |
| `claim_job` | `job_id` | claims one (exactly one agent can) and returns its brief, checks and the buyer's shared preferences |
| `deliver_job` | `job_id`, `content` | runs the brief's checks, then seals the work to the buyer and commits its hash on chain |

**Identity.** An agent is (host, session). The host comes from the MCP client's name, and the session from what the
SessionStart hook recorded for the host process. Two sessions of the same host are two agents. A reconnect of the
same session keeps its claims.

## 2. The hooks (edit-time enforcement)

`knos hook guard --client claude|codex|cursor|opencode|copilot` reads the host's pre-tool payload on stdin. For Codex
it reads `apply_patch` bodies and the write targets of shell commands; for the Copilot cloud agent, `edit`, `create` and
`bash` (template: `.github/hooks/knos.json.example`). Git's `pre-commit` and `pre-push` run `knos hook commit`, the
commit-time guard for writes no hook sees.
- **Exit 2:** refuses an edit to a file that another agent's live claim covers, or any edit once a Pro spend cap is
  reached. The reason is one line, e.g. `knos: src/parser/x.py is claimed by claude/3f9a1c2e since 14:02 (the parser
  rewrite). Ask them, or take other work; the claim lapses in 22 min. A person can release it: knos done --all`.
- **Exit 0:** everything else, including a missing store, an old version, a crash or an unreadable payload. Those also
  write one line to `~/.knos/hook.log`.

The deny output follows each host's hook format:
- Claude Code: `hookSpecificOutput.permissionDecision = "deny"`.
- Codex: the same `hookSpecificOutput` shape, plus exit 2.
- Cursor: `permission = "deny"`.
- OpenCode: the plugin throws.
- Copilot: `permissionDecision = "deny"`, plus exit 2.

`knos hook start --client claude` (SessionStart) records the session and prints what is claimed and recently noted. It
always exits 0.

## 3. The Python library

```python
from knos.core import Claims

with Claims(repo=".", who="my-agent", session="run-42") as claims:
    taken, holder = claims.take("the parser", paths=["src/parser/**"])
    if not taken:
        print(holder["who"], "holds", holder["globs"])
    elif claims.holder("src/parser/lex.py") is None:
        ...  # yours to edit
    claims.release()
```

`take` is the same single transaction the MCP server uses: of many callers reaching for overlapping paths at once,
exactly one wins.

## Data on disk (all under `~/.knos`, never in your repo)

| file | what |
|---|---|
| `<repo>-<hash>/memory.db` | the repo's Sibyl memory store (shared by its worktrees) |
| `<repo>-<hash>/claims.db` | claims, sessions and claim events |
| `<repo>-<hash>/read.db` | what has been read already, so nothing is written twice |
| `backups/` | `knos init` and `knos reset` copies |
| `meter.db`, `budget.json`, `licence.json`, `agents.json`, `agentpay.db`, `wallets/` | Knos Pro (`wallets/` holds keys, owner-only) |
| `sibyl-pro.json` | the Sibyl Pro Knos bought for this machine's paying wallets (simulated on testnets) |
| `jobs/` | jobs: `relay/` (briefs and sealed deliveries), `jobs.json` (your job ids), `memory/` (buyer preferences), `worker-*.db` (a worker's memory of its jobs), `tempo-worker.key` (owner-only) |
| `team/` | the team member key (owner-only), team salts and the mirror's database |

## 4. The team registry on Solana

A team is one [Solana Attestation Service](https://github.com/solana-foundation/solana-attestation-service) credential
(program `22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG`) named `knos-<16 hex>`. Its authority is the owner key and its
authorized signers are the member keys (at most 30: the signer list is rewritten in one transaction). It has four
schemas of its own:

| schema | nonce | data |
|---|---|---|
| `knos.claim.v1` | `unit_hash` | `unit_hash` (VecU8 32), `ancestors` (VecU8 8·k), `holder_hash` (VecU8 32), `lease_until` (I64), `kind` (U8: 0 file, 1 dir) |
| `knos.renew.v1` | `sha256(claim ‖ new_lease_until)` | claim address, `holder_hash`, `lease_until` |
| `knos.member.v1` | the member's public key | name box (secretbox under a salt-derived key), salt box (sealed to the member) |
| `knos.record.v1` | `sha256(holder ‖ period_start)` | `holder_hash`, `period_start`, taken, finished, abandoned, collisions, spent (micro-USD), `merkle_root` |

Hashes:

- `unit = casefold(NFC(repo-relative POSIX path))`.
- `unit_hash = sha256(team_salt ‖ repo_id ‖ unit)`.
- `repo_id` is 32 random bytes in `.knos/team.json`.

Closes are compare-then-close, with [Lighthouse](https://github.com/Jac0xb/lighthouse)
(`L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95`) asserting the attestation's exact bytes in the same transaction. The
builders are `knos.team.sas`, the protocol is `knos.team.protocol`, and the API is `knos.team` (`service`, `live`,
`records`).

## 5. The Python SDK, for agents beyond code

```python
from knos.sdk import Knos

k = Knos(agent="researcher")                   # this directory is the workspace
if k.claim("task:invoice-4411"):                # generic units: file:, task:, market:, wallet:
    k.remember("invoice 4411 was a duplicate", about="invoice-4411")
    k.release("task:invoice-4411")
else:
    print("held by", k.holder)
```

`k.memory_client()` hands you the workspace's Sibyl `MemoryClient` for Sibyl's own LangGraph `BaseStore`
(`sibyl_memory_langgraph.SibylStore(client=...)`). `examples/langgraph_team.py` runs two LangGraph agents that share
that memory. One claims a task, and the other is refused and takes the next one. The models are scripted, so it runs
with no API key.

## 6. Budgets the chain enforces

- **Tempo:** an AccountKeychain access key per agent (`0xAAAAAAAA00000000000000000000000000000000`), with
  `TokenLimit{token, amount, period}` and `allowedCalls` = the token's `transferWithMemo`. Built with Tempo's own
  `pytempo`. `knos budget show` reads `getRemainingLimitWithPeriod` (selector `0xa7f72cab`).
- **Solana:** an SPL `ApproveChecked` delegate on a per-agent, non-associated vault token account.

## Composed, not reimplemented

Solana Attestation Service, Lighthouse, SPL Token, the Tempo AccountKeychain, Sibyl (its client, LangGraph `BaseStore`,
learner and linter, all through `MemoryClient`), MCP, and git hooks.

Not shipped in 0.3.0, described only as directions: Squads v4 spending limits, Solana Payment Channels, 8004-Solana and
Metaplex agent identities, Coinbase Spend Permissions on Base, ERC-8004 and a Hermes example.
