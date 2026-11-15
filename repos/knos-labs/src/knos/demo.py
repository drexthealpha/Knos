"""The whole product in one command, on a throwaway repo, in about twenty seconds.

Every line printed is a real call into the real code against real SQLite files in a temporary directory; nothing is
a transcript. If a line says an edit was refused, `guard.check` refused it while you watched. Your own repos and your
own ~/.knos are never touched: the demo runs with its own KNOS_HOME and deletes it at the end.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAUSE = 0.35

# Two of these start at the same moment, in separate processes, and both reach for the same file. The claim is one
# BEGIN IMMEDIATE transaction, so exactly one of them wins.
RACE = """
import os, sys
from knos.claims import Claims
from knos.identity import Agent
repo, who = sys.argv[1], sys.argv[2]
with Claims(repo) as c:
    took, conflict, _ = c.take(Agent(host=who, session=str(os.getpid())), "the settlement path", ["settle.py"])
print(who, "| took it" if took else "| refused, held by " + conflict.label)
"""

COLD = """
import os, sys
from knos.memory import Memory
with Memory(sys.argv[1]) as mem:
    facts = [f for f in mem.search(sys.argv[2]) if f.get("text")]
print("pid", os.getpid(), "| recalled:", facts[0]["text"] if facts else "(nothing)")
"""

RULES = """# Working here

## Testing
Never use a bare except here. Catch the specific error.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Screen:
    def __init__(self, out: Any, pause: float = PAUSE) -> None:
        self.out = out
        self.pause = pause

    def beat(self, n: int, title: str) -> None:
        self.out.print("")
        self.out.print(f"[bold]{n}. {title}[/bold]")
        time.sleep(self.pause)

    def cmd(self, text: str) -> None:
        self.out.print(f"  [dim]$[/dim] {text}", markup=True)
        time.sleep(self.pause)

    def said(self, text: str, colour: str = "") -> None:
        for line in text.splitlines() or [""]:
            self.out.print(f"      [{colour}]{line}[/{colour}]" if colour else f"      {line}")
        time.sleep(self.pause)

    def note(self, text: str) -> None:
        self.out.print(f"  [dim]{text}[/dim]")
        time.sleep(self.pause)


def _sandbox(root: Path) -> Path:
    repo = root / "demo-repo"
    repo.mkdir(parents=True)
    (repo / "risk_guard.py").write_text("def check(asset):\n    return True\n", encoding="utf-8")
    (repo / "settle.py").write_text("def settle():\n    pass\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text(RULES, encoding="utf-8")
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=False)  # noqa: E731
    git("init", "-q")
    git("config", "user.email", "demo@example.invalid")
    git("config", "user.name", "demo")
    git("add", "-A")
    git("commit", "-qm", "risk guard refuses unknown assets")
    return repo


def run(out: Any, pause: float = PAUSE) -> int:
    """The sequence. Returns an exit code. Never raises out: a failure is one line and exit 1."""
    screen = Screen(out, pause)
    home = Path(tempfile.mkdtemp(prefix="knos-demo-home-"))
    work = Path(tempfile.mkdtemp(prefix="knos-demo-"))
    was = os.environ.get("KNOS_HOME")
    os.environ["KNOS_HOME"] = str(home)
    env = {**os.environ, "KNOS_HOME": str(home), "PYTHONIOENCODING": "utf-8"}
    try:
        from . import answer, guard, refresh
        from .claims import Claims
        from .identity import Agent
        from .memory import TOPIC, Fact, Memory

        repo = _sandbox(work)
        out.print("")
        out.print("[bold]knos demo[/bold] - the whole product, on a throwaway repo. Every line is a real call.")
        out.print(f"  repo   {repo}")

        screen.beat(1, "Memory every agent shares.")
        refresh.ensure(repo, force=True, index_code=False)
        with Memory(repo) as mem:
            mem.record(Fact(text="the risk guard refuses unknown assets; we chose that after the March incident",
                            source="note", where="Claude Code said so", when=_now(), about="the risk guard"))
            mem.note_thing(TOPIC, "the risk guard", {"note": "refuses unknown assets", "when": _now()[:10]})
            found = answer.ask(repo, mem, "why does the risk guard refuse unknown assets", limit=1)
        screen.cmd('Cursor asks: "why does the risk guard refuse unknown assets?"')
        screen.said((found[0].text.strip()[:120] + "\n    " + found[0].where) if found else "(nothing)", "green")
        screen.note("Written by Claude Code, read by Cursor. One local store.")

        claude = Agent(host="claude", session="s-claude")
        cursor = Agent(host="cursor", session="s-cursor")
        screen.beat(2, "Claude Code claims the file it is about to change.")
        with Claims(repo) as c:
            took, _, mine = c.take(claude, "tighten the risk guard", ["risk_guard.py"])
        screen.cmd('remember(..., claiming=true, paths=["risk_guard.py"])')
        screen.said(f"claimed {', '.join(mine.globs) if mine else '?'} for {mine.holds_min if mine else '?'} min", "green")

        screen.beat(3, "Cursor tries to edit it. The edit is refused; its question is still answered.")
        verdict = guard.check(repo, str(repo / "risk_guard.py"), cursor)
        screen.cmd("Cursor: edit risk_guard.py")
        screen.said(f"allowed = {verdict.allow}", "red")
        screen.said(verdict.reason or "", "red")
        own = guard.check(repo, str(repo / "risk_guard.py"), claude)
        screen.cmd("Claude Code: edit risk_guard.py")
        screen.said(f"allowed = {own.allow}  (its own claim never blocks it)", "green")

        screen.beat(4, "Two processes reach for the same file in the same instant.")
        racer = work / "race.py"
        racer.write_text(RACE, encoding="utf-8")
        procs = [subprocess.Popen([sys.executable, str(racer), str(repo), name], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
                 for name in ("codex", "opencode")]
        for p in procs:
            line = p.communicate(timeout=60)[0].strip() or "(no output)"
            screen.said(line, "green" if "took it" in line else "red")
        screen.note("One transaction decides; exactly one wins.")

        screen.beat(5, "A process that has never seen this repo recalls it.")
        cold = work / "cold.py"
        cold.write_text(COLD, encoding="utf-8")
        got = subprocess.run([sys.executable, str(cold), str(repo), "risk guard"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", env=env, timeout=60, check=False)
        screen.said(got.stdout.strip() or "(nothing)", "green")

        screen.beat(6, "Claude Code finishes. Cursor may edit.")
        with Claims(repo) as c:
            c.release(claude)
        after = guard.check(repo, str(repo / "risk_guard.py"), cursor)
        screen.cmd("done()")
        screen.said(f"Cursor: edit risk_guard.py -> allowed = {after.allow}", "green")

        out.print("")
        out.print("  Try it on your own repo:  knos init")
        out.print("")
        return 0
    except Exception as why:  # a demo that crashes teaches nothing; say what broke in one line
        out.print(f"knos demo stopped: {type(why).__name__}: {why}", markup=False)
        return 1
    finally:
        if was is None:
            os.environ.pop("KNOS_HOME", None)
        else:
            os.environ["KNOS_HOME"] = was
        from .paths import remove_tree

        remove_tree(work)
        remove_tree(home)
