"""What every agent is told at the start of a session, before it asks anything.

A `SessionStart` hook runs once when a session opens. It does two things:

  - it records the host's `session_id` against the host process (`claims.Claims.record_session`), which is how the
    MCP server that host starts learns which session it serves (`identity.py`);
  - it prints the live claims and the most recent notes, which the host puts into the session's own context. It prints
    nothing when there is nothing claimed and nothing written down.

It never fails a session: any error exits 0, writes one line to ~/.knos/hook.log and prints nothing. It imports only
the store, since it is on the path of opening every session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CLAIMS = 6
DECISIONS = 3


def _payload() -> dict:
    """The hook's JSON input when a host sent one (Claude Code does); {} from a terminal."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        got = json.loads(raw) if raw.strip() else {}
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def _lines(repo) -> list[str]:
    from .claims import Claims, claims_db
    from .memory import Memory

    said: list[str] = []
    if claims_db(repo).exists():
        with Claims(repo) as c:
            live = c.live()[:CLAIMS]
        if live:
            said.append("Files other agents are holding here right now:")
            for one in live:
                where = ", ".join(one.globs[:3]) or "(advisory, no files)"
                said.append(f"  - {where}: {one.description} - {one.label}, lapses in about {max(1, round(one.minutes_left))} min")
            said.append("")
            said.append("Editing a claimed file is refused by the knos guard. Claim what you are about to change with "
                        "remember(claiming=true, paths=[...]) and call done() when you finish.")

    def said_in(row: dict) -> str:
        return " ".join(str(row.get("note") or row.get("text") or "").split())

    from . import paths

    notes = []
    last = None
    if paths.has_store(repo):  # never create a store from a hook
        try:
            from .memory_io import last_note
            with Memory(repo) as mem:
                notes = [n for n in mem.notes() if said_in(n)]
                last = last_note(mem.client)
        except Exception:
            notes = []
    if last:
        if said:
            said.append("")
        said.append("Continuity note (where the last session left off): " + " ".join(last["text"].split())[:400])
    if notes:
        if said:
            said.append("")
        said.append("Recently written down here:")
        for note in notes[:DECISIONS]:
            said.append(f"  - {said_in(note)[:160]}")
    return said


def main(argv: list[str] | None = None) -> int:
    """Record the session, print the notice. Never fail the session."""
    try:
        from . import identity, paths
        from .claims import Claims

        event = _payload()
        client = "claude"
        args = list(sys.argv[1:] if argv is None else argv)
        if "--client" in args and args.index("--client") + 1 < len(args):
            client = args[args.index("--client") + 1]
        repo = paths.repo_here(Path(event["cwd"]) if event.get("cwd") else None)
        if repo is None:
            return 0
        agent = identity.for_hook(client, event)
        if agent.session:
            with Claims(repo) as c:
                c.record_session(agent.host, agent.session, agent.anchor)
        if paths.has_store(repo) and (repo / ".knos" / "playbooks").is_dir():
            from .memory import Memory
            from .sibyl import import_playbooks
            with Memory(repo) as mem:  # accepted team playbooks, committed to the repo, into Sibyl REFERENCE
                import_playbooks(mem, repo)
        said = _lines(repo)  # claims live in claims.db, so they are told even before the repo's memory is read
        if said:
            sys.stdout.write("knos, this repo's shared memory:\n" + "\n".join(said) + "\n")
    except Exception as exc:
        try:
            from .guard import log
            log(f"session start: {type(exc).__name__}: {exc}")
        except Exception:
            pass
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
