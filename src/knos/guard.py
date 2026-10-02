"""The edit guard: refuse an edit to files another agent has claimed. Nothing else.

Every host ships a hook that runs before a tool call and can refuse it:

    Claude Code   PreToolUse on Edit|Write|MultiEdit|NotebookEdit   permissionDecision "deny", or exit 2
    Codex         PreToolUse on apply_patch and shell commands      permissionDecision "deny", or exit 2
    Cursor        preToolUse                                        permission "deny", or exit 2
    OpenCode      tool.execute.before                               throw
    Copilot       the cloud agent's preToolUse hook (.github/hooks)  exit 2

The guard refuses one thing: a path covered by a live claim held by a different agent (`claims.py`, `identity.py`),
including a claimed file that has been renamed. Git sees the rename, or the new file is byte-identical to the
committed one, so `git mv parser.py helper.py` does not launder the claim.

The rules it keeps (the product's invariants):

  - the agent that holds a claim is never refused (same host and the same session or host process);
  - it refuses only a verified collision, or (Knos Pro, only when a person set one) an agent spend cap that has
    been reached. Rules in CLAUDE.md, withdrawn decisions and text similarity never block;
  - it guards edits, not reads. Claude Code, Cursor and OpenCode hooks do not see shell writes (`sed -i`, `mv`, a
    script); Codex and Copilot shell writes are parsed best-effort; the commit guard is the backstop;
  - anything unexpected (no store, a crash, an old version, an unreadable payload) exits 0 and writes one line to
    ~/.knos/hook.log. A broken install must never stand between an agent and its own repository.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .identity import Agent

REFUSE = 2
ALLOW = 0

@dataclass(frozen=True)
class Verdict:
    allow: bool
    reason: str = ""
    warning: str = ""  # shown to the person on an allowed edit (team mode: "working in local-only mode")

    @property
    def code(self) -> int:
        return ALLOW if self.allow else REFUSE


def log(line: str) -> None:
    """One line in ~/.knos/hook.log; never raises."""
    try:
        with open(paths.home() / "hook.log", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")
    except Exception:
        pass


def _as_agent(who: Agent | str) -> Agent:
    if isinstance(who, Agent):
        return who
    from .identity import host_from_client
    return Agent(host=host_from_client(str(who)))


# ---- renames: a claimed file moved to a new name is still claimed -------------------

def _moved(repo: Path) -> tuple[list[str], set[str], dict[str, str]]:
    """(deleted tracked paths, untracked paths, {new: old} renames git spotted), from `git status`."""
    try:
        # --untracked-files=all: a file moved into a brand-new folder must show up as that file, not as the folder
        out = subprocess.run(["git", "status", "--porcelain", "--find-renames", "--untracked-files=all"], cwd=repo,
                             capture_output=True,
                             text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return [], set(), {}
    gone: list[str] = []
    fresh: set[str] = set()
    renamed: dict[str, str] = {}
    for line in out.splitlines():
        if len(line) < 4:
            continue
        code, name = line[:2], line[3:].strip()
        if code.startswith("R") and " -> " in name:
            old, new = (part.strip().strip('"') for part in name.split(" -> ", 1))
            renamed[new] = old
        elif "D" in code:
            gone.append(name.strip('"'))
        elif code == "??":
            fresh.add(name.strip('"'))
    return gone, fresh, renamed


def _committed(repo: Path, rel: str) -> bytes | None:
    try:
        done = subprocess.run(["git", "cat-file", "blob", f"HEAD:{rel}"], cwd=repo, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.replace(b"\r\n", b"\n") if done.returncode == 0 else None


def may_have_moved(repo: Path, claims) -> bool:
    """Cheap test before asking git: could a claimed file have been moved away since it was claimed?

    A literal claimed path that still exists was not moved. For a glob, a file moved out of a folder changes that
    folder's modification time, so if no folder under the glob's literal prefix changed since the claim was taken,
    nothing left it. Anything unsure answers True and git decides."""
    for claim in claims:
        try:
            since = datetime.fromisoformat(claim.taken_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return True
        for g in claim.globs:
            literal = not re.search(r"[*?\[]", g)
            if literal and not (repo / g).exists():
                return True
            if literal and not (repo / g).is_dir():
                continue  # a single file that is still there was not moved
            if literal:
                top = repo / g.rstrip("/")  # a folder claim covers everything under it: watch the folder
            else:
                prefix = re.split(r"[*?\[]", g, 1)[0].rsplit("/", 1)[0] if "/" in g else ""
                top = repo / prefix if prefix else repo
            if not top.is_dir():
                return True
            seen = 0
            for root, dirs, _files in os.walk(top):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "__pycache__")]
                seen += 1
                if seen > 2000:
                    return True
                try:
                    if os.stat(root).st_mtime > since - 1:
                        return True
                except OSError:
                    return True
    return False


def renamed_from(repo: Path, rel: str, is_claimed) -> str | None:
    """The claimed path `rel` used to be, when this is really a rename (git says so, or the bytes are identical)."""
    gone, fresh, renamed = _moved(repo)
    was = renamed.get(rel)
    if was is not None and is_claimed(was):
        return was
    if rel not in fresh:
        return None
    here = None
    for old in gone:
        if not is_claimed(old):
            continue
        before = _committed(repo, old)
        if before is None:
            continue
        if here is None:
            try:
                here = (repo / rel).read_bytes().replace(b"\r\n", b"\n")
            except OSError:
                return None
        if here == before:
            return old
    return None


# ---- the decision ---------------------------------------------------------------

def _since(ts: str) -> str:
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return t.strftime("%H:%M")
    except ValueError:
        return "earlier"


def refusal(rel: str, claim, was: str | None = None) -> str:
    """The one line an agent (and the person watching) reads."""
    what = f"{rel} (renamed from {was})" if was else rel
    left = max(1, round(claim.minutes_left))
    return (f"knos: {what} is claimed by {claim.label} since {_since(claim.taken_at)} ({claim.description}). "
            f"Ask them, or take other work; the claim lapses in {left} min. A person can release it: knos done --all (Knos)")


def check(repo: Path, target: str, who: Agent | str) -> Verdict:
    """Whether `who` may edit `target` in `repo`, and the one-line reason if not."""
    agent = _as_agent(who)
    repo = Path(repo).resolve()
    try:
        rel = Path(target).resolve().relative_to(repo).as_posix()
    except (ValueError, OSError):
        return Verdict(True)  # outside the repo: nothing recorded, nothing to refuse
    local = _check_local(repo, rel, agent)
    if not local.allow:
        return local
    return _check_team(repo, rel, agent)


def _check_team(repo: Path, rel: str, agent: Agent) -> Verdict:
    """Team mode (`.knos/team.json` in the repo): the claims every machine in the team placed on Solana."""
    if not (repo / ".knos" / "team.json").exists():
        return Verdict(True)
    try:
        from .team import live
    except ImportError as exc:  # solders or PyNaCl missing: say so once per edit, never block
        return Verdict(True, warning=f"team mode needs knos's Solana extras ({exc.name}); local-only (Knos)")
    try:
        rt = live.runtime(repo)
        if rt is None:
            return Verdict(True, warning="this machine has not joined the team yet: run `knos init` (Knos)")
        d = live.check(rt, rel, agent.host, agent.session or (f"pid{agent.anchor}" if agent.anchor else ""))
    except Exception as exc:
        log(f"team guard allowed {rel}: {type(exc).__name__}: {exc}")
        return Verdict(True, warning="team registry check failed: working in local-only mode (Knos)")
    if not d.allow:
        return Verdict(False, d.reason)
    if d.warning:
        log(f"team guard: {d.warning}")
    return Verdict(True, warning=d.warning)


def _check_local(repo: Path, rel: str, agent: Agent) -> Verdict:
    from .claims import Claims, claims_db

    if not claims_db(repo).exists():
        return Verdict(True)  # no local claims: nothing can be held here
    try:
        with Claims(repo) as c:
            live = [x for x in c.live() if not x.advisory and not x.held_by(agent)]
            if not live:
                return Verdict(True)
            for claim in live:
                if claim.covers(rel):
                    c.note_block(agent, rel, claim)
                    return Verdict(False, refusal(rel, claim))
            if not may_have_moved(repo, live):
                return Verdict(True)
            was = renamed_from(repo, rel, lambda p: any(x.covers(p) for x in live))
            if was is not None:
                claim = next(x for x in live if x.covers(was))
                c.note_block(agent, rel, claim)
                return Verdict(False, refusal(rel, claim, was))
    except Exception as exc:
        log(f"guard allowed {rel}: {type(exc).__name__}: {exc}")
        return Verdict(True)
    return Verdict(True)


# ---- talking to each client ------------------------------------------------------------

def target_of(client: str, event: dict) -> str:
    """The path an edit hook payload is about, or "" when it is not an edit."""
    if client == "claude":
        got = event.get("tool_input") or {}
        return str(got.get("file_path") or got.get("notebook_path") or "")
    if client == "cursor":
        tool = str(event.get("tool_name") or "").lower().replace(" ", "_")
        if tool and not any(t in tool for t in ("edit", "write", "patch", "create", "replace")):
            return ""  # reads and searches are never guarded
        if event.get("file_path"):
            return str(event["file_path"])
        got = event.get("tool_input") or event.get("arguments") or {}
        return str(got.get("file_path") or got.get("path") or got.get("target_file") or "")
    got = event.get("args") or event.get("tool_input") or {}
    return str(got.get("filePath") or got.get("file_path") or got.get("path") or "")


_PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.MULTILINE)


def patch_paths(patch: str) -> list[str]:
    """Every file an apply_patch body touches: updated, added, deleted, and the destination of a move."""
    return [a or b for a, b in _PATCH_FILE.findall(patch or "")]


_WRITERS_ALL = {"rm", "touch", "unlink", "shred", "mv"}  # every non-flag argument (mv: sources vanish)
_WRITERS_LAST = {"cp", "install", "ln", "rsync"}                     # the last argument is written


def shell_writes(command: str) -> list[str]:
    """Files a shell command visibly writes: redirections, tee, sed -i/perl -i, cp/mv/rm/touch/truncate, git mv/rm, dd, install, rsync.
    Best effort by design: a script that writes files is not seen, and the commit guard is the backstop for those."""
    import shlex

    try:
        lex = shlex.shlex(command or "", posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return []
    out: list[str] = []
    seg: list[str] = []

    def flush() -> None:
        words = list(seg)
        while words and "=" in words[0] and not words[0].startswith("-"):  # FOO=bar cmd
            words.pop(0)
        if words and words[0] in ("sudo", "command", "env", "nohup", "time"):
            words.pop(0)
        if not words:
            return
        cmd, args = words[0].rsplit("/", 1)[-1], words[1:]
        plain = [a for a in args if not a.startswith("-")]
        if cmd == "git" and args[:1] in (["mv"], ["rm"]):
            out.extend(a for a in args[1:] if not a.startswith("-"))
        elif cmd == "truncate":
            files = []
            idx = 0
            while idx < len(args):
                a = args[idx]
                if a in ("-s", "--size", "-r", "--reference") and idx + 1 < len(args):
                    idx += 2
                    continue
                if not a.startswith("-"):
                    files.append(a)
                idx += 1
            out.extend(files)
        elif cmd == "install":
            files = []
            target_dir = None
            is_d = False
            idx = 0
            while idx < len(args):
                a = args[idx]
                if a in ("-d", "--directory"):
                    is_d = True
                    idx += 1
                    continue
                if a in ("-t", "--target-directory") and idx + 1 < len(args):
                    target_dir = args[idx + 1]
                    idx += 2
                    continue
                if a.startswith("--target-directory="):
                    target_dir = a.split("=", 1)[1]
                    idx += 1
                    continue
                if a in ("-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix") and idx + 1 < len(args):
                    idx += 2
                    continue
                if not a.startswith("-"):
                    files.append(a)
                idx += 1
            if target_dir:
                out.append(target_dir)
            elif is_d:
                out.extend(files)
            elif len(files) >= 2:
                out.append(files[-1])
        elif cmd == "rsync":
            files = []
            idx = 0
            while idx < len(args):
                a = args[idx]
                if a in ("-e", "--rsh", "--exclude", "--exclude-from", "--include", "--include-from",
                         "--filter", "--log-file", "--write-batch", "--read-batch", "--temp-dir",
                         "--timeout", "-T") and idx + 1 < len(args):
                    idx += 2
                    continue
                if not a.startswith("-"):
                    files.append(a)
                idx += 1
            if len(files) >= 2:
                dest = files[-1]
                if not (":" in dest and not dest.startswith("./")):
                    out.append(dest)
        elif cmd in ("cp", "ln"):
            files = []
            target_dir = None
            idx = 0
            while idx < len(args):
                a = args[idx]
                if a in ("-t", "--target-directory") and idx + 1 < len(args):
                    target_dir = args[idx + 1]
                    idx += 2
                    continue
                if a.startswith("--target-directory="):
                    target_dir = a.split("=", 1)[1]
                    idx += 1
                    continue
                if a in ("-S", "--suffix") and idx + 1 < len(args):
                    idx += 2
                    continue
                if not a.startswith("-"):
                    files.append(a)
                idx += 1
            if target_dir:
                out.append(target_dir)
            elif len(files) >= 2:
                out.append(files[-1])
        elif cmd in _WRITERS_ALL:
            out.extend(plain)
        elif cmd == "tee":
            out.extend(plain)
        elif cmd in ("sed", "perl") and any(a == "-i" or a.startswith("-i") or a == "--in-place" for a in args):
            out.extend(plain[1:])  # the first plain word is the script
        elif cmd == "dd":
            out.extend(a[3:] for a in args if a.startswith("of="))

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in (">", ">>", ">|", "&>", "&>>") and i + 1 < len(tokens):
            target = tokens[i + 1]
            if not target.startswith("&"):
                out.append(target)
            i += 2
            continue
        if t in (";", "&&", "||", "|", "&", "(", ")", ";;"):
            flush()
            seg = []
        elif t.isdigit() and i + 1 < len(tokens) and tokens[i + 1].startswith(">"):
            pass  # 2>file: the fd number
        else:
            seg.append(t)
        i += 1
    flush()
    return [p for p in dict.fromkeys(out) if p and not p.startswith("/dev/")]


def targets_of(client: str, event: dict) -> list[str]:
    """Every path an edit hook payload writes. Codex sends apply_patch bodies and shell commands."""
    if client == "codex":
        tool = str(event.get("tool_name") or "")
        got = event.get("tool_input") or {}
        if not isinstance(got, dict):
            got = {"command": got}
        command = got.get("command")
        if isinstance(command, list):
            command = " ".join(str(c) for c in command)
        if tool == "apply_patch":
            return patch_paths(str(command or got.get("input") or ""))
        if tool in ("Bash", "shell", "exec_command", "local_shell"):
            return shell_writes(str(command or got.get("cmd") or ""))
        if got.get("file_path"):
            return [str(got["file_path"])]
        return []
    if client == "copilot":  # Copilot cloud agent / CLI: camelCase toolName + toolArgs (VS Code shape also accepted)
        tool = str(event.get("toolName") or event.get("tool_name") or "").lower()
        args = event.get("toolArgs") if "toolArgs" in event else event.get("tool_input")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"command": args}
        if not isinstance(args, dict):
            return []
        if tool in ("bash", "powershell", "shell"):
            return shell_writes(str(args.get("command") or ""))
        if tool in ("edit", "create", "write", "str_replace_editor"):
            got = args.get("path") or args.get("file_path") or args.get("filePath")
            return [str(got)] if got else []
        return []
    one = target_of(client, event)
    return [one] if one else []


def render(client: str, verdict: Verdict) -> str:
    if verdict.allow:
        if verdict.warning and client in ("claude", "codex"):
            return json.dumps({"systemMessage": verdict.warning})
        return ""
    if client in ("claude", "codex"):
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": verdict.reason}})
    if client == "cursor":
        return json.dumps({"permission": "deny", "user_message": verdict.reason, "agent_message": verdict.reason})
    if client == "copilot":
        return json.dumps({"permissionDecision": "deny", "permissionDecisionReason": verdict.reason})
    return json.dumps({"deny": True, "reason": verdict.reason})


def decide(client: str, event: dict, repo: Path | None = None) -> Verdict:
    from . import identity

    targets = targets_of(client, event)
    if not targets:
        return Verdict(True)
    cwd = Path(repo or event.get("cwd") or Path.cwd())
    found = paths.repo_here(cwd)
    root = found if found is not None else cwd
    capped = _over_budget(root)
    if capped:
        return Verdict(False, capped)
    who = identity.for_hook(client, event)
    warning = ""
    for target in targets:
        if not Path(target).is_absolute():
            target = str((root if client not in ("codex", "copilot") else cwd) / target)
        got = check(root, target, who)
        if not got.allow:
            return got
        warning = warning or got.warning
    return Verdict(True, warning=warning)


def _over_budget(repo: Path | None = None) -> str | None:
    """Knos Pro's spend cap, when one is set: a one-line refusal once it is reached. No cap, no cost (one stat)."""
    if not (paths.home() / "budget.json").exists():
        return None
    try:
        from .pro import budget
    except ImportError:
        return None
    return budget.refusal(repo)


def once(event: dict, compute) -> Verdict:
    """One answer per tool call. A plugin hook and the repo's settings hook both run for the same edit (their commands
    differ); the first to arrive decides, and the second waits for and returns that answer, so a claim is never
    placed twice. Keyed by the host's `tool_use_id`; without one, every call decides."""
    import hashlib
    import time

    tid = str(event.get("tool_use_id") or "")
    if not tid:
        return compute()
    d = paths.home() / "hookcache"
    d.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(tid.encode()).hexdigest()[:32]
    result, lock = d / f"{key}.json", d / f"{key}.lock"
    try:
        os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        end = time.monotonic() + 40
        while time.monotonic() < end:
            try:
                got = json.loads(result.read_text(encoding="utf-8"))
                return Verdict(bool(got["allow"]), str(got.get("reason", "")), str(got.get("warning", "")))
            except (OSError, ValueError, KeyError):
                time.sleep(0.05)
        return compute()
    verdict = compute()
    tmp = result.with_suffix(".tmp")
    tmp.write_text(json.dumps({"allow": verdict.allow, "reason": verdict.reason, "warning": verdict.warning}),
                   encoding="utf-8")
    os.replace(tmp, result)
    try:  # tidy answers older than ten minutes
        cutoff = time.time() - 600
        for old in d.iterdir():
            if old.stat().st_mtime < cutoff:
                old.unlink()
    except OSError:
        pass
    return verdict


def run(client: str, stdin_text: str) -> tuple[str, int]:
    """Read one payload, return what to print and what to exit with."""
    try:
        event = json.loads(stdin_text or "{}")
    except ValueError:
        log(f"guard ({client}): unreadable payload, allowed")
        return "", ALLOW
    if not isinstance(event, dict):
        return "", ALLOW
    try:
        verdict = once(event, lambda: decide(client, event))
    except Exception as exc:
        log(f"guard ({client}) allowed: {type(exc).__name__}: {exc}")
        return "", ALLOW
    return render(client, verdict), verdict.code


# ---- installing and removing ---------------------------------------------------------

MARK = "knos-guard"


def _script() -> str | None:
    from .init import own_script

    return own_script() or shutil.which("knos")


def knos_cmd() -> list[str]:
    """How a hook calls knos: the `knos` script installed with the knos that ran `knos init` (a stale copy earlier on
    PATH is not used), by absolute path, quoted with forward slashes (a Windows path through bash loses its
    backslashes). Without a script, this interpreter with -m."""
    exe = _script()
    if exe:
        return [f'"{exe.replace(os.sep, "/")}"']
    return [f'"{sys.executable.replace(os.sep, "/")}"', "-m", "knos"]


def knos_cmd_argv() -> list[str]:
    """knos_cmd for subprocess (no shell quoting)."""
    exe = _script()
    return [exe] if exe else [sys.executable, "-m", "knos"]


def hook_cmd(kind: str, client: str) -> str:
    return " ".join(knos_cmd() + ["hook", kind, "--client", client])


def claude_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def cursor_hooks() -> Path:
    return Path.home() / ".cursor" / "hooks.json"


def codex_hooks() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"


def opencode_plugin() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "opencode" / "plugin" / "knos-guard.js"


class Unreadable(Exception):
    """A settings file that is not JSON knos understands. It is left exactly as it is, never overwritten."""


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        got = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except (ValueError, OSError) as why:
        raise Unreadable(f"{path} is not readable JSON, so knos left it alone") from why
    if not isinstance(got, dict):
        raise Unreadable(f"{path} is not a JSON object, so knos left it alone")
    return got


def _peek(path: Path) -> dict:
    """_load for reading only: an unreadable file reads as empty."""
    try:
        return _load(path)
    except Unreadable:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_claude() -> Path:
    """PreToolUse on edits -> the guard; SessionStart -> the notice (and the session record identity needs)."""
    path = claude_settings()
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = data["hooks"] = {}
    pre = [h for h in (hooks.get("PreToolUse") or []) if MARK not in json.dumps(h)]
    pre.append({"matcher": "Edit|Write|MultiEdit|NotebookEdit",
                "hooks": [{"type": "command", "command": hook_cmd("guard", "claude") + f" #{MARK}"}]})
    pre.append({"matcher": "Write|Bash",
                "hooks": [{"type": "command", "command": hook_cmd("safety", "claude") + f" #{MARK}"}]})
    hooks["PreToolUse"] = pre
    start = [h for h in (hooks.get("SessionStart") or []) if MARK not in json.dumps(h)]
    start.append({"hooks": [{"type": "command", "command": hook_cmd("start", "claude") + f" #{MARK}"}]})
    hooks["SessionStart"] = start
    stop = [h for h in (hooks.get("Stop") or []) if MARK not in json.dumps(h)]
    stop.append({"hooks": [{"type": "command", "command": hook_cmd("proof", "claude") + f" #{MARK}", "timeout": 600}]})
    hooks["Stop"] = stop
    _save(path, data)
    return path


def install_cursor() -> Path:
    path = cursor_hooks()
    data = _load(path)
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = data["hooks"] = {}
    for event in ("preToolUse", "beforeReadFile"):   # beforeReadFile only to remove what 0.1 put there
        kept = [h for h in (hooks.get(event) or []) if MARK not in json.dumps(h)]
        if event == "preToolUse":
            kept.append({"command": hook_cmd("guard", "cursor") + f" #{MARK}"})
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    _save(path, data)
    return path


def install_codex() -> Path:
    """Codex PreToolUse on apply_patch (its file edits) and Bash (shell writes). Codex asks the person to review and
    trust a new hook once before it runs."""
    path = codex_hooks()
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = data["hooks"] = {}
    pre = [h for h in (hooks.get("PreToolUse") or []) if MARK not in json.dumps(h)]
    pre.append({"matcher": "apply_patch|Bash",
                "hooks": [{"type": "command", "command": hook_cmd("guard", "codex") + f" #{MARK}", "timeout": 30,
                           "statusMessage": "Knos: checking claims"},
                          {"type": "command", "command": hook_cmd("safety", "codex") + f" #{MARK}", "timeout": 30}]})
    hooks["PreToolUse"] = pre
    stop = [h for h in (hooks.get("Stop") or []) if MARK not in json.dumps(h)]
    stop.append({"hooks": [{"type": "command", "command": hook_cmd("proof", "codex") + f" #{MARK}", "timeout": 600,
                            "statusMessage": "Knos: proving what you said is done"}]})
    hooks["Stop"] = stop
    _save(path, data)
    return path


def uninstall_codex() -> bool:
    path = codex_hooks()
    data = _peek(path)
    hooks = data.get("hooks") or {}
    took = False
    for event in ("PreToolUse", "Stop"):
        kept = [h for h in (hooks.get(event) or []) if MARK not in json.dumps(h)]
        if len(kept) != len(hooks.get(event) or []):
            took = True
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not took:
        return False
    if not hooks:
        data.pop("hooks", None)
    _save(path, data)
    return True


_OPENCODE_JS = """// knos-guard - installed by `knos init`, removed by `knos init --undo`.
// Refuses an edit to files another agent has claimed. Remove this file and nothing else changes.
export const KnosGuard = async ({{ $ }}) => ({{
  "tool.execute.before": async (input, output) => {{
    const name = String(input?.tool ?? "");
    if (!/edit|write|patch/i.test(name)) return;
    const payload = JSON.stringify({{ args: output?.args ?? {{}}, cwd: process.cwd() }});
    const done = await ${quoted}.catch((e) => e);
    if ((done?.exitCode ?? 0) === 2) {{
      const said = String(done?.stdout ?? "");
      let why = "knos: another agent has claimed this file.";
      try {{ why = JSON.parse(said).reason || why; }} catch {{}}
      throw new Error(why);
    }}
  }},
}});
"""


def install_opencode() -> Path:
    path = opencode_plugin()
    path.parent.mkdir(parents=True, exist_ok=True)
    quoted = "`echo ${payload} | " + hook_cmd("guard", "opencode") + "`"
    path.write_text(_OPENCODE_JS.format(quoted=quoted), encoding="utf-8")
    return path


def uninstall_claude() -> bool:
    path = claude_settings()
    data = _peek(path)
    hooks = data.get("hooks") or {}
    took = False
    for event in ("PreToolUse", "SessionStart", "Stop"):
        kept = [h for h in (hooks.get(event) or []) if MARK not in json.dumps(h)]
        if len(kept) != len(hooks.get(event) or []):
            took = True
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if took:
        _save(path, data)
    return took


def uninstall_cursor() -> bool:
    path = cursor_hooks()
    data = _peek(path)
    hooks = data.get("hooks") or {}
    took = False
    for event in ("preToolUse", "beforeReadFile"):
        kept = [h for h in (hooks.get(event) or []) if MARK not in json.dumps(h)]
        if len(kept) != len(hooks.get(event) or []):
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
    return {"claude": MARK in json.dumps(_peek(claude_settings()).get("hooks") or {}),
            "cursor": MARK in json.dumps(_peek(cursor_hooks()).get("hooks") or {}),
            "codex": MARK in json.dumps(_peek(codex_hooks()).get("hooks") or {}),
            "opencode": opencode_plugin().exists()}
