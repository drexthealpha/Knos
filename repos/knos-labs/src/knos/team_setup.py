"""`knos init --team`: make the team's guard travel with the repo, so every clone and every cloud session is guarded.

It writes, in the repo (commit them):
  - `.claude/settings.json` hooks: Claude Code cloud sessions ignore plugins but run these (single-repo sessions);
  - the Knos plugin at project scope: `claude plugin marketplace add drexthealpha/Knos --scope project` plus
    `claude plugin install knos@knos --scope project`, or, without the `claude` CLI, `extraKnownMarketplaces` and
    `enabledPlugins` written directly;
  - `.codex/hooks.json`: Codex loads it once the project is trusted;
and in this clone's git hooks directory the commit and push guard.

Plugin hooks and settings hooks both run for one edit (their commands differ). The guard is idempotent per
`tool_use_id`, so the second run returns the first run's answer and never places a second claim.
Every file is backed up first, so `knos init --undo` restores each byte for byte.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import commit_guard, guard

MARKETPLACE = "drexthealpha/Knos"
PLUGIN = "knos@knos"
REPO_MARK = "knos-guard-repo"

# Bare `knos` from PATH: these files are committed, so no machine's absolute path may appear in them. Exit 2 is kept
# (the refusal); anything else, including knos missing, lets the edit go ahead.
_CLAUDE_GUARD = f'knos hook guard --client claude; s=$?; [ "$s" = 2 ] && exit 2 || exit 0  # {REPO_MARK}'
_CLAUDE_START = f"knos hook start --client claude || exit 0  # {REPO_MARK}"
_CODEX_GUARD = f'knos hook guard --client codex; s=$?; [ "$s" = 2 ] && exit 2 || exit 0  # {REPO_MARK}'


def _json(path: Path) -> dict:
    return guard._load(path)


def _save(path: Path, data: dict) -> None:
    guard._save(path, data)


def claude_repo_settings(repo: Path) -> Path:
    return Path(repo) / ".claude" / "settings.json"


def codex_repo_hooks(repo: Path) -> Path:
    return Path(repo) / ".codex" / "hooks.json"


def _add_claude_hooks(data: dict) -> None:
    hooks = data.setdefault("hooks", {})
    pre = [h for h in (hooks.get("PreToolUse") or []) if REPO_MARK not in json.dumps(h)]
    pre.append({"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                "hooks": [{"type": "command", "command": _CLAUDE_GUARD, "timeout": 30}]})
    hooks["PreToolUse"] = pre
    start = [h for h in (hooks.get("SessionStart") or []) if REPO_MARK not in json.dumps(h)]
    start.append({"hooks": [{"type": "command", "command": _CLAUDE_START}]})
    hooks["SessionStart"] = start


def _add_plugin_entries(data: dict) -> None:
    markets = data.setdefault("extraKnownMarketplaces", {})
    markets["knos"] = {"source": {"source": "github", "repo": MARKETPLACE}}
    enabled = data.setdefault("enabledPlugins", {})
    enabled[PLUGIN] = True


def install(repo: Path, backups, run_claude: bool = True) -> list[str]:
    """Returns one line per thing done."""
    repo = Path(repo)
    done: list[str] = []
    settings = claude_repo_settings(repo)
    backups.keep(settings)
    used_cli = False
    claude = shutil.which("claude") if run_claude and not os.environ.get("KNOS_NO_CLAUDE_CLI") else None
    if claude:
        try:
            a = subprocess.run([claude, "plugin", "marketplace", "add", MARKETPLACE, "--scope", "project"],
                               cwd=str(repo), capture_output=True, text=True, timeout=60)
            b = subprocess.run([claude, "plugin", "install", PLUGIN, "--scope", "project"], cwd=str(repo),
                               capture_output=True, text=True, timeout=120)
            used_cli = a.returncode == 0 and b.returncode == 0
        except (OSError, subprocess.SubprocessError):
            used_cli = False
    data = _json(settings)
    if not used_cli:
        _add_plugin_entries(data)
    _add_claude_hooks(data)
    _save(settings, data)
    done.append(".claude/settings.json: Knos plugin at project scope and the guard hooks (commit it)")

    codex = codex_repo_hooks(repo)
    backups.keep(codex)
    cdata = _json(codex)
    hooks = cdata.setdefault("hooks", {})
    pre = [h for h in (hooks.get("PreToolUse") or []) if REPO_MARK not in json.dumps(h)]
    pre.append({"matcher": "apply_patch|Bash",
                "hooks": [{"type": "command", "command": _CODEX_GUARD, "timeout": 30,
                           "statusMessage": "Knos: checking claims"}]})
    hooks["PreToolUse"] = pre
    _save(codex, cdata)
    done.append(".codex/hooks.json: the Codex guard, loaded once the project is trusted (commit it)")

    d = commit_guard.hooks_dir(repo)
    for name in ("pre-commit", "pre-push"):
        backups.keep(d / name)
    commit_guard.install(repo)
    done.append("git pre-commit and pre-push: commit-time guard for raw shell writes (this clone)")
    return done


def installed(repo: Path) -> dict[str, bool]:
    return {"claude_repo": REPO_MARK in json.dumps(guard._peek(claude_repo_settings(repo))),
            "codex_repo": REPO_MARK in json.dumps(guard._peek(codex_repo_hooks(repo))),
            "commit": commit_guard.installed(repo)}


def uninstall(repo: Path) -> list[str]:
    """Take out only knos's own entries (for files edited since init, which --undo cannot restore byte for byte)."""
    repo = Path(repo)
    done = []
    for path, events in ((claude_repo_settings(repo), ("PreToolUse", "SessionStart")),
                         (codex_repo_hooks(repo), ("PreToolUse",))):
        data = guard._peek(path)
        hooks = data.get("hooks") or {}
        took = False
        for event in events:
            kept = [h for h in (hooks.get(event) or []) if REPO_MARK not in json.dumps(h)]
            if len(kept) != len(hooks.get(event) or []):
                took = True
                if kept:
                    hooks[event] = kept
                else:
                    hooks.pop(event, None)
        if took:
            if not hooks:
                data.pop("hooks", None)
            _save(path, data)
            done.append(str(path))
    done += [str(p) for p in commit_guard.uninstall(repo)]
    return done
