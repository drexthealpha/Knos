"""The Stop hook `knos init` installs.

    knos hook proof --client <host>    the agent may not finish while its last message claims something Knos cannot
                                       prove. Knos runs the checks itself; the agent's word is not evidence. After 3
                                       blocks on unchanged evidence it lets the stop through with a warning that names
                                       what is unproven, so an agent cannot be trapped by a check it cannot fix (a red
                                       CI it does not own, a dead URL).

One contract, many hosts. Each host sends its own JSON on stdin when a turn ends and reads its own answer; `_read`
turns the first into what `stop` judges and `_say` turns the verdict into the second. The shapes, and below them the
page each was read from on 2026-10-05 (claude and codex are as Knos 0.3.14 shipped them and were not read again;
integrations/hosts/README.md has the same table, with what is unconfirmed):

    host      event it sends (the fields Knos reads)                           "not done yet", as that host reads it
    claude    Stop: cwd, session_id, transcript_path | last_assistant_message   {"decision":"block","reason":...}
    codex     Stop: cwd, session_id, last_assistant_message                     {"decision":"block","reason":...}
    cursor    afterAgentResponse: text, conversation_id (kept for the stop)     nothing
              stop: status, conversation_id, workspace_roots                    {"followup_message":...}
    gemini    AfterAgent: cwd, session_id, prompt_response                      {"decision":"deny","reason":...}
    copilot   agentStop: cwd, sessionId, transcriptPath, stopReason             {"decision":"block","reason":...}
              (VS Code runs the same file as Stop: cwd, sessionId,              {"hookSpecificOutput":{"hookEventName":
              transcript_path, hookEventName)                                    "Stop","decision":"block","reason":...}}
    hermes    pre_verify: cwd, session_id, extra.final_response                 {"action":"continue","message":...}
              pre_llm_call: cwd (no check is run: the record is read)           {"context": what Sibyl remembers}
    goose     Stop: session_id, last_assistant_message                          {"decision":"block","reason":...}
    opencode  what .opencode/plugins/knos.js sends on session.idle              {"decision":"block","reason":...}
    windsurf  post_cascade_response: trajectory_id, tool_info.response          plain text, shown to the person: this
                                                                                host's post hooks cannot hold a turn
    aider     nothing (it is aider's test command, run after each edit)        the text, and exit code 1

    https://cursor.com/docs/agent/hooks                        https://geminicli.com/docs/hooks/reference/
    https://docs.github.com/en/copilot/reference/hooks-configuration
    https://code.visualstudio.com/docs/copilot/customization/hooks
    https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks
    https://goose-docs.ai/docs/guides/context-engineering/hooks/
    https://opencode.ai/docs/plugins/                          https://docs.devin.ai/desktop/cascade/hooks
    https://aider.chat/docs/usage/lint-test.html

Every answer leaves with exit code 0 except aider's, whose only signal is the code. Anything unexpected allows: a
broken install must never trap an agent.

What Knos refused before on this repository is remembered in Sibyl (knos.proof.history: the journal and the state
document) and read here on every stop, in every later session, whatever the host: a check a past refusal named is run
again even when the message does not mention it, and a block says what failed last time. With that memory gone,
nothing is owed.

A hook is a local aid, and a person can remove it. What cannot be removed by the agent is the same check at the merge:
prove.yml's `check` job runs it on the pull request, on GitHub (knos.judge.gate).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MAX_BLOCKS = 3


def _payload() -> dict:
    try:
        got = json.loads(sys.stdin.read() or "{}")
        return got if isinstance(got, dict) else {}
    except ValueError:
        return {}


def _repo(cwd: str) -> Path | None:
    p = Path(cwd or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return d
    return None


def _said(rec) -> str:
    """The assistant's text in one transcript line, or "". Claude Code writes {"type":"assistant","message":{"content":
    [{"type":"text","text":...}]}}. Copilot's and VS Code's transcript lines are not documented: the two shapes read
    here ({"type":"assistant.message","data":{"content":...}} and a bare {"role":"assistant","content":...}) are
    unconfirmed, and a line in neither shape is skipped, which allows the stop."""
    if not isinstance(rec, dict):
        return ""
    kind = rec.get("type")
    msg = rec.get("message") if kind == "assistant" else rec.get("data") if kind == "assistant.message" else \
        rec if rec.get("role") == "assistant" else None
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    parts = [content] if isinstance(content, str) else [b.get("text", "") for b in content or []
                                                        if isinstance(b, dict) and b.get("type") == "text"] \
        if isinstance(content, list) else []
    return "\n".join(p for p in parts if isinstance(p, str) and p)


def last_message(payload: dict) -> str:
    """The agent's last message: most hosts send it; Claude Code, Copilot and VS Code name the transcript, whose last
    assistant text it is."""
    for k in ("last_assistant_message", "last_message"):
        if isinstance(payload.get(k), str):
            return payload[k]
    path = payload.get("transcript_path")
    if not path or not Path(path).exists():
        return ""
    text = ""
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            joined = _said(json.loads(line))
        except ValueError:
            continue
        if joined.strip():
            text = joined
    return text


def _state_path(session: str) -> Path:
    from .. import paths
    d = paths.home() / "proof-state"
    d.mkdir(parents=True, exist_ok=True)
    return d / (re.sub(r"[^\w.-]", "_", session or "default")[:80] + ".json")


def stop(payload: dict, store=None, runners=None) -> tuple[str, str]:
    """('allow'|'block'|'warn', message)."""
    from . import engine, history
    text = last_message(payload)
    repo = _repo(payload.get("cwd", ""))
    if not text or repo is None:
        return "allow", ""
    if store is None:
        try:
            store = history.SibylStore.for_repo(repo)
        except Exception:  # noqa: BLE001 - no store: still prove, just without memory
            store = history.NullStore()
    v = engine.evaluate(repo, text, store, runners)
    if not v.claim.says_done:
        return "allow", ""
    v, owed = _with_owed(repo, v, store, runners)
    told = _remember(repo, text, v, store)
    if v.ok:
        if v.results:
            _state_path(payload.get("session_id", "")).unlink(missing_ok=True)
        return "allow", ""
    sp = _state_path(payload.get("session_id", ""))
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    n = st.get("count", 0) + 1 if st.get("digest") == v.digest else 1
    msg = "Knos could not prove what your last message claims:\n" + v.explain()
    if owed:
        msg += "\nrun because an earlier claim here was refused on it (Knos remembers that in Sibyl): " + ", ".join(owed)
    if told:
        msg += "\n" + told
    if n > MAX_BLOCKS:   # blocked MAX_BLOCKS times on this exact evidence: let it stop, loudly
        sp.unlink(missing_ok=True)
        return "warn", msg + f"\nKnos blocked this {MAX_BLOCKS} times on unchanged evidence; stopping anyway. " \
                             "Say plainly what is not done."
    sp.write_text(json.dumps({"digest": v.digest, "count": n}), encoding="utf-8")
    return "block", msg + "\nFix it, or say plainly what is not done. Knos runs these checks itself; your word is not " \
                          "evidence."


def _with_owed(repo: Path, v, store, runners):
    """The verdict with the checks an earlier refusal here named and this message did not ask for, run now. A check
    stays owed until a verdict shows it passing, so a "done" cannot step around what failed last session."""
    from . import engine, history
    have = {r.name for r in v.results}
    names = sorted(history.owed(store) - have)
    if not names:
        return v, []
    cfg = engine.config(repo)
    results = v.results + [engine.run_check(n, repo, v.claim, cfg, runners, store) for n in names]
    return engine.Verdict(all(r.ok for r in results), v.claim, results, v.required_by_history), names


def _remember(repo: Path, text: str, v, store) -> str:
    """Write this verdict to the journal and return what the record now says. The verdict stands if the store is full."""
    from . import checks, history
    if not v.results:
        return ""
    try:
        before = history.briefing(store)
        (history.accept if v.ok else history.refuse)(
            store, checks.head(repo), text, [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in v.results])
        return before
    except Exception as why:  # noqa: BLE001 - a full or locked store never traps an agent, and never clears a verdict
        _log(f"proof hook: the verdict was not remembered: {type(why).__name__}: {why}")
        return ""


# ---- one contract, each host's words ---------------------------------------------------------------------------------

CLIENTS = ("claude", "codex", "cursor", "gemini", "copilot", "vscode", "hermes", "goose", "opencode", "windsurf", "aider")
AIDER_CLAIM = "Done. All tests pass."     # aider has no message to read: its test command stands for this claim


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _read(client: str, p: dict) -> dict | None:
    """A host's event as `stop` reads it: {"cwd", "session_id", "last_assistant_message" or "transcript_path"}. None
    when the event is not an agent saying it has finished (a person interrupted it, the run failed)."""
    if client == "cursor" and p.get("status") not in (None, "completed"):
        return None
    if client in ("copilot", "vscode") and p.get("stopReason") == "user_interrupt":
        return None
    roots = p.get("workspace_roots")
    cwd = p.get("cwd") or (roots[0] if isinstance(roots, list) and roots and isinstance(roots[0], str) else "")
    session = next((str(p[k]) for k in ("session_id", "sessionId", "conversation_id", "trajectory_id") if p.get(k)), client)
    out = {"cwd": cwd if isinstance(cwd, str) else "", "session_id": f"{client}-{session}" if client not in ("claude", "codex") else session}
    said = (p.get("last_assistant_message"), p.get("last_message"), p.get("prompt_response"),
            _dict(p.get("extra")).get("final_response"), _dict(p.get("tool_info")).get("response"),
            AIDER_CLAIM if client == "aider" else None)
    text = next((v for v in said if isinstance(v, str)), None)
    if text is None and client == "cursor":
        text = _kept(out["session_id"])
    if text is not None:
        out["last_assistant_message"] = text
    path = p.get("transcript_path") or p.get("transcriptPath")
    if isinstance(path, str):
        out["transcript_path"] = path
    return out


def _keep_path(session: str) -> Path:
    return _state_path(session).with_suffix(".said")


def _kept(session: str) -> str | None:
    """What Cursor's afterAgentResponse said last in this conversation: its stop event carries no message."""
    try:
        return _keep_path(session).read_text(encoding="utf-8")
    except OSError:
        return None


def _say(client: str, verdict: str, msg: str, p: dict) -> tuple[str, int]:
    """(what to print, exit code): the verdict as this host reads it. "" where the host has no word for it."""
    if verdict == "allow":
        return "", 0
    block, j = verdict == "block", json.dumps
    if client == "aider":
        return msg, 1 if block else 0
    if client == "windsurf":
        return "Knos: " + msg, 0
    if client == "cursor":
        return (j({"followup_message": msg}) if block else ""), 0
    if client == "hermes":
        return (j({"action": "continue", "message": msg}) if block else ""), 0
    if client == "gemini":
        return j({"decision": "deny", "reason": msg} if block else {"systemMessage": msg}), 0
    if client == "vscode" or (client == "copilot" and "hookEventName" in p):
        return j({"hookSpecificOutput": {"hookEventName": "Stop", "decision": "block", "reason": msg}} if block
                 else {"systemMessage": msg}), 0
    if client in ("copilot", "goose", "opencode"):
        return (j({"decision": "block", "reason": msg}) if block else ""), 0
    return j({"decision": "block", "reason": msg} if block else {"systemMessage": msg}), 0


def _briefing(cwd: str, store=None) -> str:
    """What Sibyl remembers of this repository's refused claims, for a host that can be told before the agent speaks."""
    from . import history
    repo = _repo(cwd)
    if repo is None:
        return ""
    return history.briefing(store if store is not None else history.SibylStore.for_repo(repo))


def respond(client: str, payload: dict, store=None, runners=None) -> tuple[str, int]:
    """One host event in, that host's answer out: (stdout, exit code)."""
    name = payload.get("hook_event_name") or payload.get("agent_action_name") or payload.get("event")
    if client == "cursor" and name == "afterAgentResponse":
        if isinstance(payload.get("text"), str):
            _keep_path(f"cursor-{payload.get('conversation_id') or 'cursor'}").write_text(payload["text"], encoding="utf-8")
        return "", 0
    if client == "hermes" and name == "pre_llm_call":
        told = _briefing(str(payload.get("cwd") or ""), store)
        return (json.dumps({"context": "Knos, from Sibyl's memory of this repository: " + told}) if told else ""), 0
    event = _read(client, payload)
    if event is None:
        return "", 0
    verdict, msg = stop(event, store, runners)
    out, code = _say(client, verdict, msg, payload)
    if verdict == "warn" and not out:
        print("Knos: " + msg, file=sys.stderr)      # a host with no word for a warning still shows a hook's stderr
    return out, code


def _client(args: list[str]) -> str:
    named = args[args.index("--client") + 1] if "--client" in args[:-1] else "claude"
    return named if named in CLIENTS else "claude"


def main_proof(args: list[str]) -> int:
    client = _client(args)
    payload = {} if client == "aider" else _payload()     # aider gives a test command a terminal, not an event
    try:
        out, code = respond(client, payload)
    except Exception as why:  # noqa: BLE001 - never trap an agent on a Knos bug
        _log(f"proof hook error: {type(why).__name__}: {why}")
        return 0
    if out:
        print(out)
    return code


def _log(line: str) -> None:
    try:
        from .. import paths
        with open(paths.home() / "hook.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
