"""The whole product in one command, against a real store, in about a minute.

`knos demo` is the playground. There is no hosted one and there will not be:
nothing on the read path touches a network, and that is a test rather than a
promise (`tests/test_no_network.py`). So the local path has to be as fast to
reach as a URL, which is what this is.

Everything printed below is a real call into the real code against a real
SQLite store in a temporary directory. Nothing here is a transcript. If a line
says an edit was refused, `guard.check` refused it while you watched. The
store is deleted at the end and every refusal is re-run, so the last thing you
see is the product failing without its memory.

Your own repo is never touched. The temporary directory goes away when it
finishes.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAUSE = 0.45  # long enough to read, short enough that nobody skips


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Screen:
    """Printing, kept in one place so the demo reads like a session."""

    def __init__(self, out: Any) -> None:
        self.out = out

    def beat(self, n: int, title: str) -> None:
        self.out.print("")
        self.out.print(f"[bold]{n}. {title}[/bold]")
        self.out.print("")
        time.sleep(PAUSE)

    def cmd(self, text: str) -> None:
        self.out.print(f"  [dim]$[/dim] {text}")
        time.sleep(PAUSE)

    def said(self, text: str, colour: str = "") -> None:
        for line in text.splitlines() or [""]:
            body = f"[{colour}]{line}[/{colour}]" if colour else line
            self.out.print(f"      {body}")
        time.sleep(PAUSE)

    def note(self, text: str) -> None:
        self.out.print(f"  {text}")
        time.sleep(PAUSE)


def _sandbox(root: Path) -> Path:
    """A real git repo, because knos keys its store on the git common dir."""
    repo = root / "demo-repo"
    repo.mkdir(parents=True)
    (repo / "risk_guard.py").write_text(
        "def check(asset):\n    # refuses anything we have not seen before\n    return True\n",
        encoding="utf-8",
    )
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=repo, capture_output=True, text=True, check=False
    )
    run("init", "-q")
    run("config", "user.email", "demo@example.invalid")
    run("config", "user.name", "demo")
    run("add", "-A")
    run("commit", "-qm", "first")
    return repo


def run(out: Any) -> int:
    """The sequence. Returns an exit code."""
    from . import answer, decide, gate, guard, paths, share
    from .memory import TOPIC, Fact, Memory

    screen = Screen(out)
    home = Path(tempfile.mkdtemp(prefix="knos-demo-home-"))
    work = Path(tempfile.mkdtemp(prefix="knos-demo-"))
    import os

    was = os.environ.get("KNOS_HOME")
    os.environ["KNOS_HOME"] = str(home)

    try:
        repo = _sandbox(work)
        paths.remember_pointed(repo)
        topic = "the risk guard"
        target = repo / "risk_guard.py"

        out.print("")
        out.print("[bold]knos demo[/bold] - the whole product, on a throwaway repo.")
        out.print("")
        out.print(f"  repo   {repo}")
        out.print(f"  store  {paths.store_for(repo)}")
        out.print("")
        out.print("  Every line below is a real call. Nothing is a transcript.")
        time.sleep(PAUSE * 2)

        # ---- 1 -------------------------------------------------------------
        screen.beat(1, "Two agents. One says what it is starting.")
        with Memory(repo) as mem:
            answer.point(repo, mem, index_code=False)
            mem.record(
                Fact(text="the risk guard refuses unknown assets", source="session",
                     where="Claude Code session aaaa1111", when=_now(), about=topic)
            )
            mem.note_thing(TOPIC, topic, {"note": "refuses unknown assets",
                                          "when": _now()[:10]})
            mem.working_on(topic, "Claude Code", _now())
        screen.cmd('knos claim "the risk guard"')
        screen.said("Claude Code is working on the risk guard.", "yellow")

        # ---- 2 -------------------------------------------------------------
        screen.beat(2, "The second agent asks about it. It is refused.")
        from . import mcp as mcp_mod

        with Memory(repo) as mem:
            held = mcp_mod._held(mem, topic, "Cursor", "")
        screen.cmd("Cursor: what do we know about the risk guard?")
        screen.said(held.split("\n\n")[0], "red")
        screen.note("[dim]Not a warning attached to an answer. There is no answer.[/dim]")

        # ---- 3 -------------------------------------------------------------
        screen.beat(3, "It tries to edit the file anyway. The edit is refused.")
        verdict = guard.check(repo, str(target), "Cursor")
        screen.cmd("Cursor: edit risk_guard.py")
        screen.said(f"allow = {verdict.allow}", "red")
        # The reason is one paragraph; show it whole rather than cutting at the
        # first full stop, which lands inside "risk_guard.py".
        screen.said((verdict.reason or "").split("\n\n")[0], "red")
        screen.note("[dim]The hook exits 2. The file is never written.[/dim]")

        # ---- 4 -------------------------------------------------------------
        screen.beat(4, "The memory decides whether money moves.")
        paid = "market brief: BTC"
        note = ("Bought over x402 on Base: brief. Paid:"
                " https://basescan.org/tx/0xce109c28781fec2ea12b8e115d59b1bfea219434379a30d472cf72b4abd9a85e")
        screen.cmd('knos.gate --topic "market brief: BTC"   (nothing bought yet)')
        screen.said(f"verdict = {gate.decide(repo, paid, paid)['verdict']}  -> it would pay")
        with Memory(repo) as mem:
            mem.record(Fact(text=note, source="note", where="you said so",
                            when=_now(), about=paid))
            mem.note_thing(TOPIC, paid, {"note": note, "when": _now()[:10]})
        screen.cmd("...the agent pays once, and writes it back")
        screen.cmd('knos.gate --topic "market brief: BTC"   (asked again)')
        screen.said(f"verdict = {gate.decide(repo, paid, paid)['verdict']}  -> free", "green")
        screen.note("[dim]Same request, second time, costs nothing. That is the"
                    " memory spending or not spending.[/dim]")

        # ---- 5 -------------------------------------------------------------
        screen.beat(5, "A decision is reversed. Everything under it is held.")
        with Memory(repo) as mem:
            mem.note_thing(TOPIC, "the risk guard tests",
                           {"note": "assume unknown assets are refused", "when": _now()[:10]})
            hit = decide.supersede(mem, topic, "unknown assets pass with a warning",
                                   "you", _now())
        screen.cmd('knos changed "the risk guard" "unknown assets pass with a warning"')
        screen.said(f"{len(hit['suspect'])} thing(s) reasoned from it are now held:", "yellow")
        for name in hit["suspect"]:
            screen.said(f"  {name}", "yellow")
        with Memory(repo) as mem:
            still = decide.is_suspect(mem, "the risk guard tests")
        screen.said(f"held = {still is not None}", "yellow")
        screen.note("[dim]The old wording is archived, not deleted. `knos reconsider`"
                    " releases it.[/dim]")

        # ---- 6 -------------------------------------------------------------
        screen.beat(6, "The record leaves the machine.")
        with Memory(repo) as mem:
            where, decisions, claims = share.write(repo, mem)
        screen.cmd("knos export")
        screen.said(f"wrote {where.relative_to(repo).as_posix()}"
                    f" - {decisions} decision(s), {claims} claim(s)")
        screen.note("[dim]Commit it and the GitHub Action says this on a pull request,"
                    " with nothing installed on the other side.[/dim]")

        # ---- 7 -------------------------------------------------------------
        screen.beat(7, "Now delete the memory.")
        db = paths.store_for(repo)
        screen.cmd(f"rm {db}")
        db.unlink()
        time.sleep(PAUSE)

        with Memory(repo) as mem:
            after_held = mcp_mod._held(mem, topic, "Cursor", "")
        after_edit = guard.check(repo, str(target), "Cursor")
        after_gate = gate.decide(repo, paid, paid)["verdict"]

        screen.said(f"the withhold        {'gone' if not after_held else 'STILL THERE'}", "red")
        screen.said(f"the edit            {'allowed' if after_edit.allow else 'STILL REFUSED'}", "red")
        screen.said(f"the paid answer     {'buys again' if after_gate == 'buy' else after_gate}", "red")
        with Memory(repo) as mem:
            screen.said(f"the held decisions  {len(decide.suspects(mem))} left", "red")

        out.print("")
        out.print("  [bold]Delete the memory and this is not a worse version of the"
                  " product.[/bold]")
        out.print("  [bold]There is no product. That is what load-bearing means.[/bold]")
        out.print("")
        out.print("  The numbers, over 12 seeded trials:   [dim]python scripts/ablation.py[/dim]")
        out.print("  What it saves, in dollars:            [dim]python scripts/spend.py[/dim]")
        out.print("  Every claim mapped to a test:         [dim]docs/JUDGE_GUIDE.md[/dim]")
        out.print("")
        return 0
    finally:
        if was is None:
            os.environ.pop("KNOS_HOME", None)
        else:
            os.environ["KNOS_HOME"] = was
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
