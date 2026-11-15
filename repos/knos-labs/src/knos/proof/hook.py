"""The hooks `knos init` installs for proof.

    knos hook proof --client claude|codex    Stop: the agent may not finish while its last message claims something
                                             Knos cannot prove. After 3 blocks on unchanged evidence it lets the stop
                                             through with a warning, so an agent cannot be trapped by a check it
                                             cannot fix (a red CI it does not own, a flaky URL).
    knos hook safety --client claude|codex   PreToolUse: refuses overwriting a file this session never read, and
                                             deleting anything outside the repository (the system temp dir excepted).

Both read the hook's JSON on stdin and answer the way Claude Code and Codex read hook output: a Stop block is
{"decision": "block", "reason": ...}; a refused tool call is exit 2 with the reason on stderr. Anything unexpected
allows: a broken install must never trap an agent.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import tempfile
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


def last_message(payload: dict) -> str:
    """The agent's last message: Codex sends it; Claude Code names the transcript, whose last assistant text it is."""
    for k in ("last_assistant_message", "last_message"):
        if isinstance(payload.get(k), str):
            return payload[k]
    path = payload.get("transcript_path")
    if not path or not Path(path).exists():
        return ""
    text = ""
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        if rec.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        content = msg.get("content")
        parts = [content] if isinstance(content, str) else [b.get("text", "") for b in content or []
                                                            if isinstance(b, dict) and b.get("type") == "text"]
        joined = "\n".join(p for p in parts if p)
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
    if v.ok:
        if v.results:
            _state_path(payload.get("session_id", "")).unlink(missing_ok=True)
            try:
                pr_receipt(repo, v, text)
            except Exception as why:  # noqa: BLE001 - the receipt link is a convenience; never block a true done
                _log(f"pr receipt: {type(why).__name__}: {why}")
        return "allow", ""
    sp = _state_path(payload.get("session_id", ""))
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    n = st.get("count", 0) + 1 if st.get("digest") == v.digest else 1
    msg = "Knos could not prove what your last message claims:\n" + v.explain()
    if n > MAX_BLOCKS:   # blocked MAX_BLOCKS times on this exact evidence: let it stop, loudly
        sp.unlink(missing_ok=True)
        return "warn", msg + f"\nKnos blocked this {MAX_BLOCKS} times on unchanged evidence; stopping anyway. " \
                             "Say plainly what is not done."
    sp.write_text(json.dumps({"digest": v.digest, "count": n}), encoding="utf-8")
    return "block", msg + "\nFix it, or say plainly what is not done. Knos runs these checks itself; your word is not " \
                          "evidence."


RECEIPT_MARK = "knos-receipt:"
BOT_LOGINS = ("github-actions", "github-actions[bot]", "app/github-actions")


def _gh(repo: Path, *args: str, inp: str | None = None) -> str | None:
    import subprocess
    try:
        r = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, input=inp, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def pr_receipt(repo: Path, v, claim: str, gh=_gh, publish=None) -> str | None:
    """On a proven "done": if the current branch has an open pull request, add the receipt link to its body with
    `gh pr edit`, from the author's side (works from a fork; the maintainer installs nothing). The receipt is
    attested on devnet with the agent's own key (KNOS_MEMBER_KEY); when that cannot pay, the line carries the evidence
    root instead. Idempotent per evidence root. Off with KNOS_PR_RECEIPT=0. Returns the line added, or None."""
    if os.environ.get("KNOS_PR_RECEIPT", "1") == "0":
        return None
    out = gh(repo, "pr", "view", "--json", "number,body,state,comments")
    if not out:
        return None
    pr = json.loads(out)
    if pr.get("state") != "OPEN":
        return None
    from . import checks
    from . import receipt as rc
    root = rc.merkle_root(rc.leaves(rc.evidence(v.results)))
    body = pr.get("body") or ""
    if root.hex() in body:
        return None
    paid = [m.group(0) for c in pr.get("comments") or [] if c.get("author", {}).get("login") in BOT_LOGINS
            for m in [re.search(r"https://\S+/receipt\.html\?a=\w+", c.get("body") or "")] if m]
    if paid and paid[-1] in body:
        return None
    if paid:   # the escrow paid this PR: link the payment's receipt (the relay attested it), no new attestation
        publish = lambda: paid[-1].rsplit("=", 1)[1]  # noqa: E731
    if publish is None:
        def publish():
            from ..jobs import net
            from ..team import rpc
            return rc.publish(rpc.CLUSTERS["devnet"], net.key(), root, checks.head(repo), claim)[1]
    try:
        line = f"{RECEIPT_MARK} {rc.page_url(publish())} (evidence root {root.hex()})"
    except Exception:  # noqa: BLE001 - no devnet SOL: still record what was proven
        line = f"{RECEIPT_MARK} evidence root {root.hex()} at {checks.head(repo)[:12]}"
    new = body.rstrip() + "\n\n" + line + "\n"
    if gh(repo, "pr", "edit", str(pr["number"]), "--body-file", "-", inp=new) is None:
        return None
    return line


def main_proof(args: list[str]) -> int:
    payload = _payload()
    try:
        verdict, msg = stop(payload)
    except Exception as why:  # noqa: BLE001 - never trap an agent on a Knos bug
        _log(f"proof hook error: {type(why).__name__}: {why}")
        return 0
    if verdict == "block":
        print(json.dumps({"decision": "block", "reason": msg}))
    elif verdict == "warn":
        print(json.dumps({"systemMessage": msg}))
    return 0


# ---- safety: unread overwrites and deletes outside the repo -------------------------------------------------------

_DELETE = re.compile(r"(?:^|[;&|]\s*|\bsudo\s+)(rm|rmdir|del|rd|erase|remove-item|ri|unlink|shred)\b(.*?)(?=$|[;&|])",
                     re.IGNORECASE | re.DOTALL)


def _read_in_session(transcript: str | None, target: Path) -> bool:
    if not transcript or not Path(transcript).exists():
        return True   # nothing to judge by: allow
    want = os.path.normcase(str(target.resolve()))
    for line in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        if '"tool_use"' not in line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        for b in (rec.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in (
                    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
                fp = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                if fp and os.path.normcase(str(Path(fp).resolve())) == want:
                    return True
    return False


def _outside(repo: Path, cwd: Path, arg: str) -> bool:
    if not arg or arg.startswith("-"):
        return False
    p = Path(os.path.expandvars(os.path.expanduser(arg.strip("'\""))))
    p = (p if p.is_absolute() else cwd / p).resolve()
    tmp = Path(tempfile.gettempdir()).resolve()
    inside = lambda base: p == base or base in p.parents
    return not inside(repo) and not inside(tmp)


def safety(payload: dict) -> str | None:
    """A refusal, or None to allow."""
    tool = payload.get("tool_name") or ""
    inp = payload.get("tool_input") or {}
    cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    repo = _repo(str(cwd)) or cwd
    if tool == "Write" and inp.get("file_path"):
        target = Path(inp["file_path"])
        target = target if target.is_absolute() else cwd / target
        if target.exists() and not _read_in_session(payload.get("transcript_path"), target):
            return f"knos: {target} exists and this session never read it. Read it first, then write."
    if tool in ("Bash", "shell", "local_shell") or "command" in inp:
        cmd = inp.get("command") or ""
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        for m in _DELETE.finditer(cmd):
            try:
                args = shlex.split(m.group(2), posix=os.name != "nt")
            except ValueError:
                args = m.group(2).split()
            for a in args:
                if _outside(repo, cwd, a):
                    return f"knos: refusing to delete {a}: it is outside this repository ({repo})."
    return None


def main_safety(args: list[str]) -> int:
    try:
        why = safety(_payload())
    except Exception as e:  # noqa: BLE001
        _log(f"safety hook error: {type(e).__name__}: {e}")
        return 0
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


def _log(line: str) -> None:
    try:
        from .. import paths
        with open(paths.home() / "hook.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
