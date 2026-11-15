"""The Claude Agent SDK as one of many parallel attempts on a Knos task, stopped at the source when it tries to cheat.

Claude Agent SDK, Python (code.claude.com/docs/en/agent-sdk/python and /hooks, read 14 Oct 2026): `pip install
claude-agent-sdk`; `query(prompt=..., options=ClaudeAgentOptions(...))` yields messages ending in a ResultMessage
(session_id, total_cost_usd, result, is_error); `mcp_servers={"name": {"type": "stdio", "command": ..., "args": [...]}}`;
hooks are `{"PreToolUse": [HookMatcher(matcher="Write|Edit", hooks=[callback])]}` and a callback
`async def cb(input_data, tool_use_id, context)` returns `{}` to allow or
`{"hookSpecificOutput": {"hookEventName": input_data["hook_event_name"], "permissionDecision": "deny",
"permissionDecisionReason": ...}}` to block; "If any hook returns deny, the operation is blocked regardless of other hooks".

What Knos adds: the agent may change only the task's editable file. A PreToolUse hook (`guard`) refuses any write to
tests, test fixtures, conftest.py, CI configuration, lock and sealed files, and any shell command that touches them,
the cheats Knos's referee would otherwise catch after the fact (src/knos/cheats). The agent gets the Knos MCP server
(`knos mcp`) to read the task's terms and judge its own tree locally; the referee, not the agent, decides.

`SdkProposer` plugs into `python -m knos.autoresearch run TASK --proposer sdk:claude` (proposers.from_spec).
"""
from __future__ import annotations

import asyncio
import re
from pathlib import PurePosixPath

from ..autoresearch.proposers import Candidate, Context, parse_reply, prompt

MODEL = "claude-opus-5-5"
GUARDED_TOOLS = "Write|Edit|MultiEdit|NotebookEdit|Bash"
# what an attempt may never change: the judge's own ground (the referee's cheat rules name the same files)
PROTECTED = re.compile(r"(^|/)(tests?|testing|spec|__snapshots__|fixtures)(/|$)|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$"
                       r"|(^|/)\.github/|(^|/)\.gitlab-ci\.yml$|(^|/)(pytest\.ini|tox\.ini|setup\.cfg|noxfile\.py)$"
                       r"|(^|/)\.knos/|(^|/)knos\.ya?ml$|\.lock$|(^|/)(uv\.lock|poetry\.lock|package-lock\.json)$")


def _paths(tool: str, tool_input: dict) -> list[str]:
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        p = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return [str(PurePosixPath(p.replace("\\", "/")))] if p else []
    if tool == "Bash":
        return re.findall(r"[\w./-]+", tool_input.get("command", ""))
    return []


WRITES = re.compile(r"\bsed\s+-i|>|\btee\b|\brm\b|\bmv\b|\bcp\b|\btruncate\b|\bdd\b|\bchmod\b|\bgit\s+(checkout|restore|rm|apply|mv)\b"
                    r"|\bpatch\b|\bperl\s+-[a-z]*i|write_text|open\([^)]*['\"][wa]")


def refusal(tool: str, tool_input: dict, editable: str | None = None) -> str | None:
    """Why this tool call is refused, or None. A write to anything but `editable` (when given) is refused too. A shell
    command is refused when it would write (redirect, sed -i, rm, mv, cp, git checkout ...) and names a protected
    path; running the tests (`pytest tests/`) is reading them, and allowed."""
    if tool == "Bash" and not WRITES.search(tool_input.get("command", "")):
        return None
    for p in _paths(tool, tool_input):
        if PROTECTED.search(p):
            return f"{p} is part of the judge (tests, fixtures, CI or sealed files): an attempt may not change it"
    if editable and tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        target = _paths(tool, tool_input)
        if target and not target[0].endswith(editable):
            return f"only {editable} may change in this task"
    return None


def make_guard(editable: str | None = None):
    async def guard(input_data, tool_use_id, context):
        why = refusal(input_data.get("tool_name", ""), input_data.get("tool_input") or {}, editable)
        if why is None:
            return {}
        return {"hookSpecificOutput": {"hookEventName": input_data.get("hook_event_name", "PreToolUse"),
                                       "permissionDecision": "deny", "permissionDecisionReason": why}}
    return guard


def options(cwd: str, editable: str | None = None, model: str = MODEL, max_turns: int = 30):
    """ClaudeAgentOptions for one attempt: the Knos MCP server, the guard, edits accepted inside `cwd` only."""
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher  # type: ignore[import-not-found]
    return ClaudeAgentOptions(
        cwd=cwd, model=model, max_turns=max_turns, permission_mode="acceptEdits",
        allowed_tools=["Read", "Glob", "Grep", "Write", "Edit", "Bash", "mcp__knos__knos_find_work", "mcp__knos__knos_bounty", "mcp__knos__knos_verify"],
        mcp_servers={"knos": {"type": "stdio", "command": "knos", "args": ["mcp"]}},
        hooks={"PreToolUse": [HookMatcher(matcher=GUARDED_TOOLS, hooks=[make_guard(editable)])]},
        system_prompt=("You are one of several independent attempts on a research task judged by the Knos referee. Change only the "
                       "editable file. Tests, fixtures, CI and sealed files belong to the judge; changing them is refused."))


async def attempt(task_prompt: str, cwd: str, editable: str | None = None, query=None, opts=None) -> dict:
    """Run one attempt; {text, session_id, cost_usd, is_error}. `query`/`opts` stand in for the SDK in tests."""
    if query is None:
        from claude_agent_sdk import query as sdk_query  # type: ignore[import-not-found]
        query = sdk_query
    opts = opts if opts is not None else options(cwd, editable)
    out = {"text": "", "session_id": None, "cost_usd": None, "is_error": True}
    async for m in query(prompt=task_prompt, options=opts):
        if type(m).__name__ == "ResultMessage":
            out = {"text": getattr(m, "result", "") or "", "session_id": getattr(m, "session_id", None),
                   "cost_usd": getattr(m, "total_cost_usd", None), "is_error": bool(getattr(m, "is_error", False))}
    return out


class SdkProposer:
    """An autoresearch proposer backed by the Agent SDK: the same prompt CommandProposer sends, the reply parsed the
    same way, but run in-process with the guard, so a cheating edit is refused before it is written."""

    def __init__(self, cwd: str = ".", query=None, opts=None):
        self.name, self.cwd, self._query, self._opts = "sdk:claude", cwd, query, opts

    def propose(self, ctx: Context) -> Candidate | None:
        got = asyncio.run(attempt(prompt(ctx), self.cwd, ctx.editable, self._query, self._opts))
        if got["is_error"] or not got["text"].strip():
            return None
        src, change = parse_reply(got["text"])
        return Candidate({ctx.editable: src}, self.name, change)
