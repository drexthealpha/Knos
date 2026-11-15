"""One recorded end-of-turn event per host, written from that host's documentation (read 2026-10-05), and where the
answer to it is found. None was captured from a running host: integrations/hosts/README.md says so.

EVENTS[client] = (source, confirmed, event, reason)
    source      the page the event's fields were read from
    confirmed   False when a part Knos depends on is not on that page (the reason is beside it, and the test that
                uses the event carries `unconfirmed` in its name)
    event       the JSON the host writes to the hook's stdin; `{cwd}` and `{said}` are filled in by `event()`
    reason      how to get the "not done yet" text out of the hook's stdout, as the host would
"""
from __future__ import annotations

import json
from pathlib import Path

EVENTS: dict[str, tuple[str, bool, dict, object]] = {
    # https://code.claude.com/docs/en/hooks (as Knos 0.3.14 shipped it; not read again)
    "claude": ("Claude Code hooks reference", True,
               {"session_id": "s1", "cwd": "{cwd}", "hook_event_name": "Stop", "stop_hook_active": False,
                "last_assistant_message": "{said}"},
               lambda out: out["decision"] == "block" and out["reason"]),
    "codex": ("Codex hooks", True,
              {"session_id": "s1", "cwd": "{cwd}", "hook_event_name": "Stop", "last_assistant_message": "{said}"},
              lambda out: out["decision"] == "block" and out["reason"]),
    # stop carries no message: afterAgentResponse (`text`) is sent first and kept. Both shapes are on the page.
    "cursor": ("https://cursor.com/docs/agent/hooks", True,
               {"conversation_id": "c1", "generation_id": "g1", "model": "auto", "hook_event_name": "stop",
                "cursor_version": "2.0", "workspace_roots": ["{cwd}"], "user_email": None, "transcript_path": None,
                "status": "completed", "loop_count": 0},
               lambda out: set(out) == {"followup_message"} and out["followup_message"]),
    "gemini": ("https://geminicli.com/docs/hooks/reference/ (last updated 2026-04-10)", True,
               {"session_id": "s1", "transcript_path": "", "cwd": "{cwd}", "hook_event_name": "AfterAgent",
                "timestamp": "2026-10-05T12:00:00Z", "prompt": "fix the parser", "prompt_response": "{said}",
                "stop_hook_active": False},
               lambda out: out["decision"] == "deny" and out["reason"]),
    # agentStop names a transcript and no message; the lines of that transcript are not documented
    "copilot": ("https://docs.github.com/en/copilot/reference/hooks-configuration", False,
                {"sessionId": "s1", "timestamp": 1790000000000, "cwd": "{cwd}", "transcriptPath": "{transcript}",
                 "stopReason": "no_more_steps"},
                lambda out: out["decision"] == "block" and out["reason"]),
    "vscode": ("https://code.visualstudio.com/docs/copilot/customization/hooks (2026-09-30)", False,
               {"sessionId": "s1", "timestamp": "2026-10-05T12:00:00Z", "cwd": "{cwd}", "hookEventName": "Stop",
                "transcript_path": "{transcript}", "stop_hook_active": False},
               lambda out: out["hookSpecificOutput"]["hookEventName"] == "Stop"
               and out["hookSpecificOutput"]["decision"] == "block" and out["hookSpecificOutput"]["reason"]),
    "hermes": ("https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks", True,
               {"hook_event_name": "pre_verify", "tool_name": None, "tool_input": None, "session_id": "sess_abc123",
                "cwd": "{cwd}", "profile": "default",
                "extra": {"platform": "cli", "model": "m", "coding": True, "attempt": 0, "final_response": "{said}",
                          "changed_paths": ["src/auth.py"]}},
               lambda out: out["action"] == "continue" and out["message"]),
    # the event has no folder: Knos takes the one the hook is started in, which the page does not state
    "goose": ("https://goose-docs.ai/docs/guides/context-engineering/hooks/", False,
              {"event": "Stop", "session_id": "abc-123", "last_assistant_message": "{said}"},
              lambda out: out["decision"] == "block" and out["reason"]),
    # what .opencode/plugins/knos.js sends; the plugin's own reading of session.idle is not on the page
    "opencode": ("https://opencode.ai/docs/plugins/", False,
                 {"cwd": "{cwd}", "session_id": "ses_1", "last_assistant_message": "{said}"},
                 lambda out: out["decision"] == "block" and out["reason"]),
    # no folder in the event either, and the answer is text for the person: the host reads nothing back
    "windsurf": ("https://docs.devin.ai/desktop/cascade/hooks", False,
                 {"agent_action_name": "post_cascade_response", "trajectory_id": "t1", "execution_id": "e1",
                  "timestamp": "2026-10-05T12:00:00Z", "model_name": "m", "tool_info": {"response": "{said}"}},
                 None),
}

CURSOR_SAID = {"conversation_id": "c1", "generation_id": "g1", "hook_event_name": "afterAgentResponse",
               "workspace_roots": ["{cwd}"], "text": "{said}"}
HERMES_BEFORE = {"hook_event_name": "pre_llm_call", "tool_name": None, "tool_input": None, "session_id": "sess_abc123",
                 "cwd": "{cwd}", "profile": "default",
                 "extra": {"user_message": "carry on", "conversation_history": [], "is_first_turn": True, "model": "m",
                           "platform": "cli"}}
NEEDS_CWD = ("goose", "windsurf")         # hosts whose event names no folder
TRANSCRIPT = {"copilot": lambda said: {"type": "assistant.message", "data": {"content": said}},
              "vscode": lambda said: {"role": "assistant", "content": said}}


def _fill(value, words: dict):
    if isinstance(value, str):
        for k, v in words.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, words) for k, v in value.items()}
    return [_fill(v, words) for v in value] if isinstance(value, list) else value


def event(client: str, repo: Path, said: str, session: str = "") -> dict:
    """The host's event for an agent that just said `said` in `repo`. `session` makes it another session's."""
    words = {"cwd": str(repo), "said": said, "transcript": ""}
    if client in TRANSCRIPT:
        path = repo.parent / f"{client}-transcript{session}.jsonl"
        path.write_text(json.dumps({"type": "user.message", "data": {"content": "go"}}) + "\n"
                        + json.dumps(TRANSCRIPT[client](said)) + "\n", encoding="utf-8")
        words["transcript"] = str(path)
    got = _fill(EVENTS[client][2], words)
    for key in ("session_id", "sessionId", "conversation_id", "trajectory_id"):
        if session and key in got:
            got[key] += session
    return got


def deliver(client: str, repo: Path, said: str, store, runners, session: str = "") -> tuple[str, int]:
    """Send the host's events for one finished turn through the hook, as the host would: (stdout, exit code)."""
    from knos.proof import hook
    if client == "aider":
        return hook.respond("aider", {}, store, runners)
    if client == "cursor":
        first = _fill(CURSOR_SAID, {"cwd": str(repo), "said": said})
        first["conversation_id"] += session
        assert hook.respond("cursor", first, store, runners) == ("", 0)
    return hook.respond(client, event(client, repo, said, session), store, runners)


def reason(client: str, out: str) -> str:
    """The "not done yet" text in the hook's stdout, read as the host reads it; "" when it says nothing."""
    if not out:
        return ""
    if client in ("aider", "windsurf"):
        return out
    got = EVENTS[client][3](json.loads(out))
    assert got, f"{client} would not read this as a block: {out}"
    return got
