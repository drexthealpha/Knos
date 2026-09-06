"""Refusing the edit itself, not only the answer.

Everywhere else in knos the rule is the same one: knos owns what it knows, so
the most it can do about work somebody else claimed is decline to be the
source. That is true of MCP and it is the honest limit of a server — the
protocol gives it no way to see an edit, let alone stop one.

Every one of these clients ships a hook system anyway, outside MCP, and each
one can refuse a tool call before it runs:

    Claude Code   PreToolUse       permissionDecision "deny", or exit 2
    Cursor        preToolUse       permission "deny", or exit 2
    OpenCode      tool.execute.before   throw

So the guard is not a second product. It is the claim knos already holds,
consulted one step earlier, at the moment an agent reaches for the file
instead of at the moment it asks a question about it.

Two things get refused, and only two:

  - a path whose subject somebody else has claimed, matched by the same
    `same_subject` the withhold uses, so a claim on "the parser" covers
    `src/parser/lexer.py` exactly as it covers a question about the parser;
  - a path a rule in this repo's own CLAUDE.md or AGENTS.md forbids in
    words a machine can check — "never edit `src/generated/`" is a pattern,
    "write idiomatic code" is not, and this only ever reads the first kind.

Nothing here guesses. A rule with no path in it is not a rule this module
has an opinion about, and a claim that does not match is not a claim.

This is off unless somebody runs `knos guard --install`. A hook that denies
an edit wrongly is worse than no hook, so it is never written by
`knos connect` and `knos guard --uninstall` takes it back out.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import answer, paths, rules
from .memory import Memory

# Both hook runners treat 2 as "refuse this call", whatever else is printed.
# Every client also has its own JSON shape and knos prints the right one, but
# the exit code is what actually holds if a schema moves under us.
REFUSE = 2
ALLOW = 0

CLIENTS = ("claude", "cursor", "opencode")

# A rule earns an opinion here only if it says not to do something *and*
# names where. Both halves are required: "never commit secrets" has no path
# and "src/generated/ is generated" has no prohibition.
_NO = re.compile(
    r"\b(never|do not|don't|dont|no one should|must not|mustn't|avoid|forbidden|off[- ]limits)\b",
    re.I,
)
# A path inside backticks. Bare words are not paths: "never touch config"
# would match half a repo, so the rule has to have marked it as a path.
_PATH = re.compile(r"`([^`\n]+)`")
# What separates a path from an ordinary backticked word like `pytest`.
_LOOKS_LIKE_PATH = re.compile(r"[/\\*]|\.[A-Za-z0-9]{1,6}$")


@dataclass(frozen=True)
class Verdict:
    """What the guard decided, and the sentence a person will read."""

    allow: bool
    reason: str = ""

    @property
    def code(self) -> int:
        return ALLOW if self.allow else REFUSE


def _subject(path: str) -> str:
    """The part of a path a claim could plausibly be about.

    Matching the whole path pulls in `src`, `lib` and `app`, which almost
    every claim shares a stem with once identifiers are split. The file and
    the directory holding it are what somebody means when they claim "the
    parser", so those are what gets compared.
    """
    p = Path(str(path).replace("\\", "/"))
    parts = [p.stem]
    if p.parent.name:
        parts.append(p.parent.name)
    return " ".join(parts)


def path_rules(repo: Path) -> list[tuple[str, str]]:
    """(glob, where) for every rule in this repo that forbids a path.

    Read out of the same CLAUDE.md and AGENTS.md `rules.read` already parses,
    so a repo that has told knos its rules has told the guard at the same
    time and there is no second file to keep in step.
    """
    out: list[tuple[str, str]] = []
    for rule in rules.read(repo):
        if not _NO.search(rule.text):
            continue
        for candidate in _PATH.findall(rule.text):
            token = candidate.strip().lstrip("./")
            if not token or not _LOOKS_LIKE_PATH.search(token):
                continue
            glob = token.rstrip("/") + "/*" if token.endswith("/") else token
            out.append((glob, rule.where))
    return out


def _forbidden(repo: Path, rel: str) -> tuple[str, str] | None:
    for glob, where in path_rules(repo):
        if fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(rel, f"*/{glob}"):
            return glob, where
    return None


def check(repo: Path, target: str, who: str) -> Verdict:
    """Whether `who` may edit `target` in `repo`, and why not if not."""
    repo = Path(repo).resolve()
    try:
        rel = Path(target).resolve().relative_to(repo).as_posix()
    except (ValueError, OSError):
        # Outside the repo entirely. Knos has nothing recorded about it and
        # refusing on no evidence is the failure mode this whole module has
        # to avoid.
        return Verdict(True)

    hit = _forbidden(repo, rel)
    if hit:
        glob, where = hit
        return Verdict(
            False,
            f"{rel} is off limits: this repo's own rule at {where} says not to "
            f"touch {glob}. If the rule is wrong, change the rule.",
        )

    subject = _subject(rel)
    try:
        with Memory(repo) as mem:
            for work in mem.claims():
                topic = str(work.get("topic", ""))
                holder = str(work.get("who", "")) or "another agent"
                if not topic or holder == who:
                    continue
                if not answer.same_subject(topic, subject):
                    continue
                return Verdict(
                    False,
                    f"{rel} is part of {topic}, which {holder} claimed and is "
                    f"working on now. Ask them, or take something else. The "
                    f"claim lapses on its own in under half an hour, and "
                    f"`knos done` gives it back sooner.",
                )

            # A claim is about who is moving. This is about what was settled
            # and then reversed: work reasoned from a decision somebody has
            # since changed is exactly the work nobody thinks to revisit, so
            # the edit is held until someone says they have looked.
            from . import decide

            found = decide.is_suspect(mem, subject)
            if found is not None:
                return Verdict(False, decide.refusal(found))
    except Exception:
        # A store that cannot be read must not become a wall between an agent
        # and its own repo. Silence here is a decision: the guard is a
        # refinement on top of the claim, never a gate in front of the disk.
        return Verdict(True)

    return Verdict(True)


# --- talking to each client -------------------------------------------------


def target_of(client: str, event: dict) -> str:
    """The path a hook payload is about, or "" when it is about nothing."""
    if client == "claude":
        got = event.get("tool_input") or {}
        return str(got.get("file_path") or got.get("notebook_path") or "")
    if client == "cursor":
        if event.get("file_path"):
            return str(event["file_path"])
        got = event.get("tool_input") or event.get("arguments") or {}
        return str(got.get("file_path") or got.get("path") or "")
    got = event.get("args") or event.get("tool_input") or {}
    return str(got.get("filePath") or got.get("file_path") or got.get("path") or "")


def render(client: str, verdict: Verdict) -> str:
    """The refusal in the shape this client reads."""
    if verdict.allow:
        return ""
    if client == "claude":
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": verdict.reason,
                }
            }
        )
    if client == "cursor":
        return json.dumps(
            {
                "permission": "deny",
                "user_message": verdict.reason,
                "agent_message": verdict.reason,
            }
        )
    return json.dumps({"deny": True, "reason": verdict.reason})


def decide(client: str, event: dict, repo: Path | None = None) -> Verdict:
    """One hook call, start to finish."""
    target = target_of(client, event)
    if not target:
        return Verdict(True)
    root = Path(repo or event.get("cwd") or Path.cwd())
    # The payload names the directory the client is in, which inside a repo
    # is often a subdirectory. The claim is kept against the repo, so walk up
    # to it; `repo_here` returns None when there is no repo above us, and
    # then there is nothing recorded to refuse on anyway.
    found = paths.repo_here(root)
    if found is not None:
        root = found
    who = str(event.get("agent_type") or event.get("session_id") or client)
    return check(root, target, who)


def run(client: str, stdin_text: str) -> tuple[str, int]:
    """Read one payload, return what to print and what to exit with."""
    try:
        event = json.loads(stdin_text or "{}")
    except ValueError:
        return "", ALLOW
    if not isinstance(event, dict):
        return "", ALLOW
    verdict = decide(client, event)
    return render(client, verdict), verdict.code


# --- installing and removing ------------------------------------------------


def _knos_cmd() -> list[str]:
    """How a hook should call knos back.

    The interpreter is spelled out because a hook runs with the client's
    environment, not the shell that installed it, and `python` there may be
    a different one or none at all.
    """
    return [sys.executable, "-m", "knos.guard_hook"]


def claude_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def cursor_hooks() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def opencode_plugin() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode" / "plugin" / "knos-guard.js"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    keep = path.with_name(path.name + ".before-knos")
    shutil.copy2(path, keep)
    return keep


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        got = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


MARK = "knos-guard"


def install_claude() -> Path:
    path = claude_settings()
    _backup(path)
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    entries = [h for h in hooks.get("PreToolUse", []) if MARK not in json.dumps(h)]
    entries.append(
        {
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": " ".join(_knos_cmd() + ["--client", "claude", f"#{MARK}"]),
                }
            ],
        }
    )
    hooks["PreToolUse"] = entries
    _save(path, data)
    return path


def install_cursor() -> Path:
    path = cursor_hooks()
    _backup(path)
    data = _load(path)
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    for event in ("preToolUse", "beforeReadFile"):
        kept = [h for h in hooks.get(event, []) if MARK not in json.dumps(h)]
        kept.append(
            {"command": " ".join(_knos_cmd() + ["--client", "cursor", f"#{MARK}"])}
        )
        hooks[event] = kept
    _save(path, data)
    return path


_OPENCODE_JS = """// knos-guard - installed by `knos guard --install`, removed by --uninstall.
// Refuses an edit to work another agent has claimed, or to a path this repo's
// own CLAUDE.md / AGENTS.md forbids. Remove this file and nothing else changes.
export const KnosGuard = async ({{ $ }}) => ({{
  "tool.execute.before": async (input, output) => {{
    const name = String(input?.tool ?? "");
    if (!/edit|write|patch/i.test(name)) return;
    const payload = JSON.stringify({{ args: output?.args ?? {{}}, cwd: process.cwd() }});
    const done = await ${quoted}.catch((e) => e);
    if ((done?.exitCode ?? 0) === 2) {{
      const said = String(done?.stdout ?? "");
      let why = "knos: this work is claimed by another agent.";
      try {{ why = JSON.parse(said).reason || why; }} catch {{}}
      throw new Error(why);
    }}
  }},
}});
"""


def install_opencode() -> Path:
    path = opencode_plugin()
    _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    argv = " ".join(_knos_cmd() + ["--client", "opencode"])
    quoted = "`echo ${payload} | " + argv + "`"
    path.write_text(_OPENCODE_JS.format(quoted=quoted), encoding="utf-8")
    return path


def uninstall_claude() -> bool:
    path = claude_settings()
    data = _load(path)
    hooks = data.get("hooks") or {}
    before = json.dumps(hooks.get("PreToolUse", []))
    if MARK not in before:
        return False
    hooks["PreToolUse"] = [
        h for h in hooks.get("PreToolUse", []) if MARK not in json.dumps(h)
    ]
    if not hooks["PreToolUse"]:
        hooks.pop("PreToolUse")
    _save(path, data)
    return True


def uninstall_cursor() -> bool:
    path = cursor_hooks()
    data = _load(path)
    hooks = data.get("hooks") or {}
    took = False
    for event in ("preToolUse", "beforeReadFile"):
        kept = [h for h in hooks.get(event, []) if MARK not in json.dumps(h)]
        if len(kept) != len(hooks.get(event, [])):
            took = True
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if took:
        _save(path, data)
    return took


def uninstall_opencode() -> bool:
    path = opencode_plugin()
    if not path.exists():
        return False
    path.unlink()
    return True


def installed() -> dict[str, bool]:
    """Which clients currently have the guard wired, asked of the files."""
    claude = MARK in json.dumps((_load(claude_settings()).get("hooks") or {}))
    cursor = MARK in json.dumps((_load(cursor_hooks()).get("hooks") or {}))
    return {
        "claude": claude,
        "cursor": cursor,
        "opencode": opencode_plugin().exists(),
    }
