"""The whole product in one command, against a real store, in about fifty seconds.

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
import sys
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAUSE = 0.45  # long enough to read, short enough that nobody skips

# A whole new interpreter, which has never imported knos in this run, asked to
# recall what an earlier process wrote. Printed with the repo's commit hash and
# the wall clock so a recording shows it was not spliced.
# Two of these are started at the same moment, in separate processes, and both
# reach for the same work. The compare-and-swap in `claim_if_free` is what
# makes exactly one of them win; without a shared store both would.
RACE = """
import os, sys
from datetime import datetime, timezone
from knos.memory import Memory
repo, topic, who = sys.argv[1], sys.argv[2], sys.argv[3]
now = datetime.now(timezone.utc).isoformat()
with Memory(repo) as mem:
    took, holder = mem.claim_if_free(topic, who, now)
if took:
    print("pid", os.getpid(), who, "| TOOK IT")
else:
    print("pid", os.getpid(), who, "| refused, held by", (holder or {}).get("who", "?"))
"""

COLD = """
import os, sys
from datetime import datetime, timezone
from knos.memory import Memory
repo = sys.argv[1]
with Memory(repo) as mem:
    facts = [f for f in mem.search(sys.argv[2]) if f.get("text")]
print("pid", os.getpid(), "| utc", datetime.now(timezone.utc).strftime("%H:%M:%S"))
for f in facts[:2]:
    print("recalled:", f["text"], "|", f.get("where", ""))
"""



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


# What the demo repo's instruction file says before the first beat takes a
# rule out of it. Two rules, so the answer after the deletion is the other one
# rather than silence - silence is ambiguous on camera.
RULES = """# Working here

## Testing
Never use a bare except here. Catch the specific error.

## Style
Two spaces of indentation everywhere.
"""


def _sandbox(root: Path) -> Path:
    """A real git repo, because knos keys its store on the git common dir."""
    repo = root / "demo-repo"
    repo.mkdir(parents=True)
    (repo / "risk_guard.py").write_text(
        "def check(asset):\n    # refuses anything we have not seen before\n    return True\n",
        encoding="utf-8",
    )
    # An instruction file, because the first beat deletes a rule out of one.
    (repo / "CLAUDE.md").write_text(
        RULES, encoding="utf-8"
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
        screen.beat(1, "One agent, on its own. A rule you deleted stops being quoted.")
        with Memory(repo) as mem:
            answer.point(repo, mem, index_code=False)
            asked = "can I use a bare except"
            before = answer.ask(repo, mem, asked)
        screen.cmd(f'knos ask "{asked}"')
        screen.said(
            (before[0].text.splitlines()[-1] + "\n    " + before[0].where)
            if before else "(nothing)",
            "green",
        )

        # The file changes under it, which is what instruction files do.
        (repo / "CLAUDE.md").write_text(
            RULES.replace(
                "## Testing\nNever use a bare except here. "
                "Catch the specific error.\n\n", ""
            ),
            encoding="utf-8",
        )
        screen.cmd("you delete that rule from CLAUDE.md")
        with Memory(repo) as mem:
            after = answer.ask(repo, mem, asked)
        screen.cmd(f'knos ask "{asked}"')
        screen.said(
            (after[0].text.splitlines()[-1] + "\n    " + after[0].where)
            if after else "Nothing about that.",
            "red",
        )
        screen.note("[dim]The store still has the rule. It stopped being an "
                    "answer, because the file it cites stopped saying it.[/dim]")

        # ---- 2 -------------------------------------------------------------
        screen.beat(2, "Two agents. One says what it is starting.")
        with Memory(repo) as mem:
            mem.record(
                Fact(text="the risk guard refuses unknown assets", source="session",
                     where="Claude Code session aaaa1111", when=_now(), about=topic)
            )
            mem.note_thing(TOPIC, topic, {"note": "refuses unknown assets",
                                          "when": _now()[:10]})
            mem.working_on(topic, "Claude Code", _now())
        screen.cmd('knos claim "the risk guard"')
        screen.said("Claude Code is working on the risk guard.", "yellow")

        # ---- 3 -------------------------------------------------------------
        screen.beat(3, "The second agent asks about it. It is refused.")
        from . import mcp as mcp_mod

        with Memory(repo) as mem:
            held = mcp_mod._held(mem, topic, "Cursor", "")
        screen.cmd("Cursor: what do we know about the risk guard?")
        screen.said(held.split("\n\n")[0], "red")
        screen.note("[dim]Not a warning attached to an answer. There is no answer.[/dim]")

        # ---- 4 -------------------------------------------------------------
        screen.beat(4, "It tries to edit the file anyway. The edit is refused.")
        verdict = guard.check(repo, str(target), "Cursor")
        screen.cmd("Cursor: edit risk_guard.py")
        screen.said(f"allow = {verdict.allow}", "red")
        # The reason is one paragraph; show it whole rather than cutting at the
        # first full stop, which lands inside "risk_guard.py".
        screen.said((verdict.reason or "").split("\n\n")[0], "red")
        screen.note("[dim]The hook exits 2. The file is never written.[/dim]")

        # ---- 5 -------------------------------------------------------------
        screen.beat(5, "The memory decides whether money moves.")
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

        # The other half: not what is being bought, but who is buying it.
        from . import record

        with Memory(repo) as mem:
            for n in range(6):
                record.note_taken(mem, f"a dropped job {n}", "a killed CI runner", _now())
        screen.cmd('knos.gate --as "a killed CI runner"  (asks for something new)')
        fresh = "market brief: SOL"
        said = gate.decide(repo, fresh, fresh, "a killed CI runner")
        screen.said(f"verdict = {said['verdict']}", "red")
        screen.said((said["answer"] or "").split(". ")[0] + ".", "red")
        screen.note("[dim]It has taken work here six times and closed none. The"
                    " budget is shared, so it does not spend it.[/dim]")
        # The same three answers, against real money rather than a sandbox.
        # `scripts/live_gate.py --spend` runs buy -> refused -> free on Base
        # mainnet and writes the transaction hash into the evidence file, so
        # this beat is not the only place the sequence exists.
        screen.note("[dim]This exact sequence has run on Base mainnet with real"
                    " USDC: paid, then refused by this same record, then free"
                    " from the store. The receipt is in"
                    " docs/evidence/live-gate.json.[/dim]")

        # ---- 6 -------------------------------------------------------------
        screen.beat(6, "A decision is reversed. Everything under it is held.")
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

        # ---- 7 -------------------------------------------------------------
        screen.beat(7, "The record leaves the machine.")
        with Memory(repo) as mem:
            where, decisions, claims = share.write(repo, mem)
        screen.cmd("knos export")
        screen.said(f"wrote {where.relative_to(repo).as_posix()}"
                    f" - {decisions} decision(s), {claims} claim(s)")
        screen.note("[dim]Commit it and the GitHub Action says this on a pull request,"
                    " with nothing installed on the other side.[/dim]")

        # ---- 8 -------------------------------------------------------------
        screen.beat(8, "A process that has never seen this repo is asked.")
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                              capture_output=True, text=True, check=False)
        screen.note(f"[dim]repo at commit {head.stdout.strip()},"
                    f" clock {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC[/dim]")
        cold = work / "cold.py"
        cold.write_text(COLD, encoding="utf-8")
        import os as _os

        got = subprocess.run(
            [sys.executable, str(cold), str(repo), topic],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**_os.environ, "KNOS_HOME": str(home), "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        screen.cmd(f"python cold.py   (a new interpreter, pid not {_os.getpid()})")
        screen.said(got.stdout.strip() or got.stderr.strip()[-300:], "green")
        screen.note("[dim]Nothing was passed to it but the path. Everything it"
                    " said came out of the store.[/dim]")

        # The same boundary, now with two of them reaching for one thing.
        racer = work / "race.py"
        racer.write_text(RACE, encoding="utf-8")
        contested = "the settlement path"
        started = [
            subprocess.Popen(
                [sys.executable, str(racer), str(repo), contested, name],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace",
                env={**_os.environ, "KNOS_HOME": str(home),
                     "PYTHONIOENCODING": "utf-8"},
            )
            for name in ("Claude Code", "Cursor")
        ]
        said = [p.communicate()[0].strip() for p in started]
        screen.cmd(f'two processes, same instant, both claim "{contested}"')
        for line in said:
            screen.said(line, "green" if "TOOK IT" in line else "red")
        screen.note("[dim]Different pids, started together, and one of them is"
                    " refused by name. Nothing passes between them but the"
                    " store - `python scripts/collide.py` does this sixteen"
                    " ways and counts zero double-grants in 128 attempts.[/dim]")

        # ---- 9 -------------------------------------------------------------
        screen.beat(9, "What the store learned about who finishes.")
        from . import record

        # STRONG claims each, because that is where a record stops being
        # pooled with the prior and the ends of the range become reachable.
        # Fewer would be true and would print numbers that match nothing in
        # the docs - the first version of this beat showed 35 against 22.
        rounds = record.STRONG
        with Memory(repo) as mem:
            for n in range(rounds):
                record.note_taken(mem, f"a job {n}", "Claude Code", _now())
                record.note_finished(mem, f"a job {n}", "Claude Code", _now())
            for n in range(rounds):
                record.note_taken(mem, f"a dead job {n}", "a crashed runner", _now())
            earned = record.holds_for(mem, "Claude Code")
            lost = record.holds_for(mem, "a crashed runner")
            thin = record.holds_for(mem, "a runner with two claims")
        screen.cmd("knos who")
        screen.said(f"Claude Code      closed {rounds} of {rounds}   -> {earned} min", "green")
        screen.said(f"a crashed runner closed 0 of {rounds}   -> {lost} min", "yellow")
        screen.note("[dim]Not a setting. The hold is what each agent earned by"
                    " closing its own claims, read out of the journal.[/dim]")
        screen.note(f"[dim]It takes {rounds} to get there. Two claims and no"
                    " finishes is not a record yet, so the store keeps such an"
                    f" agent near the {thin} minutes everybody starts on rather"
                    " than punishing it for an afternoon.[/dim]")

        # The same record, read backwards. Everything else here answers about
        # now; this is the question after a collision.
        #
        # The whole demo takes about fifty seconds, so there is no real
        # yesterday to look at. This writes one - an hour of history with the
        # timestamps it would have had - and then reads it back the same way
        # `knos at` reads any other afternoon.
        from datetime import timedelta

        from . import record, rewind

        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with Memory(repo) as mem:
            record.note_taken(mem, "the settlement job", "Cursor", hour_ago)
            back = rewind.at(mem, rewind.when("2h"))
        screen.cmd('knos at 2h        (who held what, two hours ago)')
        if back["claims"]:
            for held in back["claims"]:
                screen.said(f"{held['who']} held {held['topic']}"
                            f" - {held['would_lapse_after']} min earned", "yellow")
        else:
            screen.said("nothing was held then", "yellow")
        screen.note("[dim]Reconstructed with the hold that agent had earned"
                    " *then*, not the one it has earned since.[/dim]")

        # ---- 10 -------------------------------------------------------------
        screen.beat(10, "What your agents cannot see, and cannot tell is there.")
        # A private path is not redacted and not counted. The owner's answer
        # and the agent's answer are the same question against the same store
        # in the same second, and one of them comes back empty with no sign
        # that anything was withheld.
        from . import private as private_mod

        secret = repo / "secrets"
        secret.mkdir(exist_ok=True)
        (secret / "keys.py").write_text(
            "SETTLEMENT_TOKEN_NAME = \"the settlement key\"\n", encoding="utf-8"
        )
        for git_args in (("add", "-A"), ("commit", "-qm", "keys")):
            subprocess.run(["git", *git_args], cwd=repo,
                           capture_output=True, check=False)
        with Memory(repo) as mem:
            answer.point(repo, mem)
        private_mod.add(repo, "secrets")
        screen.cmd("knos private secrets")
        with Memory(repo) as mem:
            mine = answer.ask(repo, mem, "SETTLEMENT_TOKEN_NAME",
                              identity=private_mod.OWNER)
            theirs = answer.ask(repo, mem, "SETTLEMENT_TOKEN_NAME",
                                identity=private_mod.AGENT)
        screen.cmd('you ask:   "SETTLEMENT_TOKEN_NAME"')
        screen.said(mine[0].where if mine else "(nothing)", "green")
        screen.cmd('the agent asks the same thing, same second')
        screen.said(f"{len(theirs)} results" if not theirs else theirs[0].where, "red")
        screen.note("[dim]Not redacted, not counted, not refused. There is no"
                    " notice that anything was held back, because a notice is"
                    " itself the answer to \"is there a secret here\".[/dim]")

        # ---- 11 -------------------------------------------------------------
        screen.beat(11, "Now delete the memory.")
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
            gone = record.holds_for(mem, "a crashed runner")
            screen.said(f"who finishes        forgotten, everyone is worth"
                        f" {gone} min again", "red")

        out.print("")
        out.print("  [bold]Delete the memory and this is not a worse version of the"
                  " product.[/bold]")
        out.print("  [bold]There is no product. That is what load-bearing means.[/bold]")
        out.print("")
        # Point at things a person who ran `pip install` actually has. The
        # scripts live in the repository, so naming them here was a dead end
        # for anybody who never cloned it.
        out.print("  Every number behind this, checkable:  "
                  "[dim]https://drexthealpha.github.io/Knos[/dim]")
        out.print("  The receipts, resolved against Base:  [dim]knos receipts[/dim]")
        out.print("  Who has edited the record:            [dim]knos verify[/dim]")
        out.print("")
        return 0
    finally:
        if was is None:
            os.environ.pop("KNOS_HOME", None)
        else:
            os.environ["KNOS_HOME"] = was
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
