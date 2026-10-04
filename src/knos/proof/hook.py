"""The Stop hook `knos init` installs.

    knos hook proof --client claude|codex    Stop: the agent may not finish while its last message claims something
                                             Knos cannot prove. Knos runs the checks itself; the agent's word is not
                                             evidence. After 3 blocks on unchanged evidence it lets the stop through
                                             with a warning that names what is unproven, so an agent cannot be
                                             trapped by a check it cannot fix (a red CI it does not own, a dead URL).

It reads the hook's JSON on stdin and answers the way Claude Code and Codex read hook output: a Stop block is
{"decision": "block", "reason": ...}. Anything unexpected allows: a broken install must never trap an agent.

What Knos refused before on this repository is remembered in Sibyl (knos.proof.history: the journal and the state
document) and read here on every stop, in every later session: a check a past refusal named is run again even when
the message does not mention it, and a block says what failed last time. With that memory gone, nothing is owed.

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


def _log(line: str) -> None:
    try:
        from .. import paths
        with open(paths.home() / "hook.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
