"""The knos command line.

`knos init` once, then your agents do the work. Every command here is something a person typed; knos does nothing on
its own between them. Every failure is one line that says what happened and the command that fixes it.
"""

from __future__ import annotations

import getpass
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from . import answer, builtin_reader, code, errors, help as help_text, link, paths, private, sessions
from . import version
from .memory import TOPIC, Fact, Memory, StoreGone

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False,
                  help="AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.")

# Answers quote other people's writing, which on Windows routinely contains characters the console's code page cannot
# encode. Ask for UTF-8 and replace what will not fit rather than fail on an em dash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

out = Console(soft_wrap=True, highlight=False)


class Stop(Exception):
    """A failure a person can fix: printed as one line (plus the fix), exit 1."""

    def __init__(self, said: str, fix: str = "") -> None:
        super().__init__(said)
        self.said, self.fix = said, fix


def _quote(text: str) -> None:
    out.print(text, markup=False)


@app.callback(invoke_without_command=True)
def _no_command(ctx: typer.Context,
                show_version: bool = typer.Option(False, "--version", help="print the installed version and stop")) -> None:
    """Typing `knos` on its own shows the one screen, not a usage box."""
    if show_version:
        out.print(version())
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        out.print(help_text.main())


def _stop(problem: errors.Problem) -> None:
    raise Stop(problem.said, problem.fix)


def _repo(given: str | None = None) -> Path:
    """The repo a command is about: --in when given, else the git repo this shell is in. Never another repo."""
    if given:
        repo = Path(given).expanduser().resolve()
        if not repo.is_dir():
            _stop(errors.no_such_folder(given))
        return repo
    here = paths.repo_here()
    if here is None:
        _stop(errors.nothing_indexed())
    return here  # type: ignore[return-value]


def _fresh(repo: Path, force: bool = False) -> dict | None:
    """Read what is new in the repo, showing progress on the first read. Never deletes."""
    from . import refresh

    first = not paths.has_store(repo)
    if first:
        out.print(f"[dim]First time in {repo.name}. Reading it now.[/dim]")

    def progress(note: str) -> None:
        if first or force:
            out.print(f"  {note}...", end="\r")

    counts = refresh.ensure(repo, force=force, on_progress=progress)
    if first or force:
        out.print(" " * 60, end="\r")
    return counts


def _me(repo: Path):
    """Who is typing: an agent's shell (by the host process above us) or a person at a terminal."""
    from . import identity
    from .claims import lookup_session

    agent = identity.for_cli(lookup_session(repo))
    if agent.host == "terminal":
        try:
            user = getpass.getuser()
        except Exception:
            user = "you"
        return identity.Agent(host="terminal", session=user)
    return agent


# ---- setup ------------------------------------------------------------------------------


@app.command()
def init(
    undo: bool = typer.Option(False, "--undo", help="take out everything knos init put in"),
    hosts: str = typer.Option(None, "--hosts", help="only these: claude,codex,cursor,desktop,opencode"),
    show: bool = typer.Option(False, "--print", help="show what would be written, change nothing"),
    test: bool = typer.Option(True, "--test/--no-test", help="start the server once to prove it answers"),
    read: bool = typer.Option(True, "--read/--no-read", help="read this repo into memory now (within the budget)"),
    team: bool = typer.Option(False, "--team", help="also guard this repo for everyone: repo hooks, plugin, git hooks"),
) -> None:
    """Wire knos into every agent on this machine (memory server, edit guard, session notice)."""
    from . import init as setup

    started = time.perf_counter()
    try:
        chosen = setup.pick(hosts)
    except ValueError as why:
        raise Stop(str(why), "Example:  knos init --hosts claude,cursor") from None

    if show:
        cmd = setup.server_command()
        out.print("Would add this MCP server to: " + (", ".join(setup.NAMES[h] for h in chosen) or "(no agents found)"))
        _quote(f'  "knos": {{"command": "{cmd[0]}", "args": {cmd[1:]}}}')
        out.print("and the edit guard + session notice hooks for Claude Code, Codex, Cursor and OpenCode.")
        return

    if undo:
        rep = setup.undo(chosen or list(setup.HOSTS), paths.repo_here())
        for name in rep.done:
            out.print(f"Removed from {name}.")
        if not rep.done:
            out.print("Nothing to remove: knos was not wired into any agent here.")
        for p in rep.problems:
            out.print(f"[yellow]{p}[/yellow]", markup=True)
        if rep.backups:
            out.print(f"[dim]Copies of every file as it was: {rep.backups}[/dim]")
        return

    if not chosen:
        raise Stop("No coding agent found on this machine (Claude Code, Codex, Claude Desktop, Cursor, OpenCode).",
                   "Install one, or name it:  knos init --hosts claude")
    here = paths.repo_here()
    if read and here is not None:
        from . import refresh

        try:
            counts = refresh.ensure(here, force=True, budget=setup.READ_BUDGET, index_code=False) or {}
            got = [f"{counts.get('commits', 0)} commits", f"{counts.get('sessions', 0)} things said in past sessions"]
            if counts.get("rules"):
                got.append(f"{counts['rules']} rules from CLAUDE.md / AGENTS.md")
            more = "; the rest is read on the first question" if counts.get("ran_out") else ""
            out.print(f"[green]+[/green] read {here.name} into Sibyl memory: {', '.join(got)}{more}")
        except Exception as why:  # reading is a convenience here; wiring the agents is the job
            out.print(f"[yellow]![/yellow] could not read {here.name} yet ({type(why).__name__}); "
                      "the first question reads it")
    if team and here is None:
        raise Stop("--team guards a repo: run it inside one.")
    rep = setup.install(chosen, here if team else None)
    for line in rep.done:
        out.print(f"[green]+[/green] {line}")
    if here is not None and (here / ".knos" / "team.json").exists():
        try:
            from .team.cli import join_hint

            for line in join_hint(here):
                out.print(line, markup=False)
        except Exception as why:  # the team is an extra; wiring the agents is the job
            out.print(f"[yellow]![/yellow] team setup skipped ({type(why).__name__}: {why})")
    for p in rep.problems:
        out.print(f"[yellow]![/yellow] {p}")
    if rep.backups:
        out.print(f"[dim]Copies of every file it changed: {rep.backups}   Undo:  knos init --undo[/dim]")
    if test:
        problems = setup.selftest()
        if problems:
            for p in problems:
                out.print(f"[red]self-test: {p}[/red]")
            raise typer.Exit(1)
        out.print("[green]Self-test passed:[/green] the memory server answered with its tools and the guard "
                  "allowed an empty edit.")
    for line in rep.restart:
        out.print(f"  Restart {line}")
    out.print(f"[dim]Done in {time.perf_counter() - started:.1f}s.[/dim]")
    out.print('Try it:  knos ask "what did we decide about auth?"   or   knos demo')
    if rep.problems:
        raise typer.Exit(1)


@app.command("connect", hidden=True)
def connect(show: bool = typer.Option(False, "--print"), hosts: str = typer.Option(None, "--hosts")) -> None:
    """Old name for `knos init`."""
    init(undo=False, hosts=hosts, show=show, test=True, read=True, team=False)


@app.command("guard", hidden=True)
def guard_cmd(install: bool = typer.Option(False, "--install"), uninstall: bool = typer.Option(False, "--uninstall")) -> None:
    """Old name: the guard is part of `knos init` now."""
    from . import guard

    if install:
        init(undo=False, hosts=None, show=False, test=True, read=True, team=False)
        return
    if uninstall:
        init(undo=True, hosts=None, show=False, test=False, read=False, team=False)
        return
    for name, on in guard.installed().items():
        out.print(f"  {name:<10} {'guarding' if on else 'not wired'}")
    out.print("  knos init wires it; knos init --undo takes it out.")


# ---- reading and asking -------------------------------------------------------------------


@app.command()
def point(path: str = typer.Argument(".", help="the repo to read")) -> None:
    """Catch up on a repo: read what is new since last time. Never deletes anything."""
    repo = Path(path).expanduser().resolve()
    if not repo.is_dir():
        _stop(errors.no_such_folder(path))
    started = time.perf_counter()
    counts = _fresh(repo, force=True) or {}
    took = time.perf_counter() - started
    out.print(f"Read {repo.name} in {took:.0f}s.")
    if counts.get("rules"):
        out.print(f"  {counts['rules']} rules written down in this repo")
    out.print(f"  {counts.get('sessions', 0)} new things said in agent sessions")
    out.print(f"  {counts.get('commits', 0)} new commits")
    if counts.get("code"):
        out.print(f"  {counts['code']} pieces of code structure")
    if counts.get("known"):
        out.print(f"  [dim]{counts['known']} already known, not written twice[/dim]")
    if counts.get("private"):
        out.print(f"  {counts['private']} private, kept from your agents")
    skipped = errors.report_skipped(counts.get("skipped") or [])
    if skipped:
        out.print(skipped)
    if counts.get("full"):
        out.print("[yellow]The Sibyl store is full (5 MB free tier); the oldest part was not read.[/yellow] "
                  "Make room:  knos compact   or  knos pro buy (Sibyl Pro, uncapped, is included)")


@app.command()
def reset(yes: bool = typer.Option(False, "--yes", help="really start over (a backup is kept)")) -> None:
    """Start this repo's memory over. The old store is copied to ~/.knos/backups first."""
    from . import refresh

    repo = _repo()
    if not yes:
        raise Stop(f"This starts {repo.name}'s memory over (notes included; a backup is kept).",
                   "To go ahead:  knos reset --yes")
    try:
        backup = refresh.reset(repo)
    except OSError:
        _stop(errors.busy(repo))
    out.print(f"Started {repo.name} over." + (f" Backup: {backup}" if backup else " There was no store."))
    out.print("The next question reads it again.")


@app.command()
def ask(
    question: str = typer.Argument(..., help="what you want to know"),
    path: str = typer.Option(None, "--in", help="the repo to ask about"),
    limit: int = typer.Option(8, "--limit", "-n", min=1, help="how many answers to print"),
) -> None:
    """Ask about this repo."""
    from .claims import Claims, claims_db

    repo = _repo(path)
    _fresh(repo)
    started = time.perf_counter()
    with Memory(repo) as mem:
        found = answer.ask(repo, mem, question, limit=limit)
        joined = link.cross(repo, found)
    took = (time.perf_counter() - started) * 1000
    if claims_db(repo).exists():
        me = _me(repo)
        with Claims(repo) as c:
            for x in c.about(question + "\n" + "\n".join(p.text + " " + p.where for p in found)):
                who = "You hold" if x.held_by(me) else f"{x.label} holds"
                out.print(f"[yellow]{who} {', '.join(x.globs) or '(advisory)'} ({x.description}).[/yellow]")
    if not found:
        _stop(errors.nothing_found(repo))
    for hop in joined:
        _quote(hop.text)
        out.print(f"    [dim]{hop.where}[/dim]", markup=True)
        out.print("")
    shown = {h.decision.text for h in joined}
    for p in found:
        if p.text in shown:
            continue
        text = p.text.strip().replace("\r", "")
        if len(text) > 400:
            text = text[:400].rsplit(" ", 1)[0] + "..."
        _quote(text)
        out.print("    " + f"[dim]{p.where}[/dim]", markup=True)
        out.print("")
    out.print(f"[dim]{len(found)} found in {took:.0f}ms[/dim]")
    if answer.looks_structural(question) and not code.indexed(repo):
        out.print(str(errors.structure_unread(repo)), markup=False)


@app.command()
def remember(
    fact: str = typer.Argument(..., help="something your agents should know"),
    about: str = typer.Option(None, "--about", help="what to file it under"),
) -> None:
    """Tell your agents something. Says so plainly if it could not be written."""
    from datetime import datetime, timezone

    repo = _repo()
    now = datetime.now(timezone.utc).isoformat()
    name = about or answer.topic_of(fact)
    with Memory(repo) as mem:
        written = mem.record(Fact(text=fact, source="note", where=f"you said so, {now[:10]}", when=now, about=name))
        if written is None:
            raise Stop("Not remembered: the Sibyl store is full (5 MB free tier) and nothing was written.",
                       "Make room:  knos compact   or  knos pro buy (Sibyl Pro, uncapped, is included)")
        mem.note_thing(TOPIC, name, {"note": fact, "when": now[:10]})
        near = mem.near_full()
    out.print(f"Noted, under {name}. Every agent you connect will know. Drop it:  knos forget \"{name}\"")
    if near:
        out.print("[yellow]Sibyl memory is over 80% of its 5 MB free tier.[/yellow] "
                  "Make room:  knos compact   or  knos pro buy (Sibyl Pro, uncapped, is included)")


@app.command()
def notes() -> None:
    """What your agents (and you) have written down."""
    repo = _repo()
    with Memory(repo) as mem:
        written = mem.notes()
    if not written:
        out.print("Nothing written down yet. Your agents add to this with their remember tool, or:  knos remember")
        return
    for n in written:
        _quote(f"{n['about']}: {n['note']}")
        out.print(f"    [dim]{n['when']}[/dim]")
    out.print(f"[dim]{len(written)} written down. Drop one:  knos forget <name>[/dim]")


@app.command()
def forget(about: str = typer.Argument(..., help="the note to drop")) -> None:
    """Drop something written down. It is archived, not erased."""
    repo = _repo()
    with Memory(repo) as mem:
        if not mem.remembered(about):
            raise Stop(f"Nothing written down about {about}.", "See what there is:  knos notes")
        mem.supersede(TOPIC, about, "the person dropped it")
    out.print(f"Forgotten: {about}. Your agents will not repeat it.")


@app.command()
def compact(days: int = typer.Option(30, "--older-than", help="drop notes forgotten more than this many days ago")) -> None:
    """Make room in Sibyl memory: drop long-forgotten notes and give freed space back. Nothing answers use is lost."""
    repo = _repo()
    with Memory(repo) as mem:
        got = mem.compact(days)
        capped = mem.capped
    mb = lambda b: b / (1024 * 1024)  # noqa: E731
    out.print(f"{mb(got['before']):.2f} MB -> {mb(got['after']):.2f} MB"
              + (" of Sibyl's 5 MB free tier" if capped else "") + f". Dropped {got['dropped']} forgotten note(s).")
    if got["duplicates"]:
        out.print(f"[dim]{got['duplicates']} journal entries were recorded twice; Sibyl's journal is append-only, so "
                  "they stay (answers show each once).[/dim]")
    if capped and got["after"] >= 0.8 * 5 * 1024 * 1024:
        out.print("Still over 80%. knos pro buy (Sibyl Pro, uncapped, is included)")


@app.command("private")
def private_cmd(path: str = typer.Argument(..., help="a path to keep private")) -> None:
    """Keep a path from your agents."""
    repo = _repo()
    private.add(repo, path)
    out.print(f"{path} is private. You can still search it; your agents cannot see it.")


# ---- claims ------------------------------------------------------------------------------


@app.command()
def claim(
    what: str = typer.Argument(..., help="what you are about to work on"),
    files: list[str] = typer.Option(None, "--path", "-p", help="files, folders or globs (repeatable)"),
    minutes: int = typer.Option(30, "--for", help="how long the claim holds, in minutes"),
) -> None:
    """Claim files, so every other agent's edit to them is refused until you are done."""
    from .claims import Claims

    repo = _repo()
    me = _me(repo)
    with Claims(repo) as c:
        took, conflict, mine = c.take(me, what, list(files or []) or None, holds_min=minutes)
    if not took and conflict is not None:
        from .guard import _since
        raise Stop(f"Not claimed: {', '.join(conflict.globs)} is held by {conflict.label} since "
                   f"{_since(conflict.taken_at)} ({conflict.description}).",
                   "Ask them, or take other work. A person can release it:  knos done --all")
    if mine is not None and not mine.advisory:
        held = _team_claim(repo, mine.globs, me)
        if held:
            with Claims(repo) as c:
                c.release(me, mine.id)
            raise Stop(f"Not claimed: {', '.join(mine.globs)} is held on another machine by {held}.",
                       "Ask them, or take other work.")
    if mine is None or mine.advisory:
        out.print(f"Claimed \"{what}\" as advisory: no file named in it resolved, so other agents are told but "
                  "nothing is blocked. Name files:  knos claim \"...\" -p src/parser/**")
    else:
        out.print(f"Claimed {', '.join(mine.globs)} for {mine.holds_min} min. Other agents' edits to it are refused.")
    out.print("Give it back:  knos done")


def _session_of(agent) -> str:
    return agent.session or (f"pid{agent.anchor}" if agent.anchor else "")


def _team_claim(repo: Path, globs: list[str], agent) -> str | None:
    """In a team (.knos/team.json), the same claim on Solana: who holds it when another machine's agent won."""
    try:
        from .team import live
    except ImportError:
        return None
    return live.explicit(repo, globs, agent.host, _session_of(agent))


def _team_release(repo: Path, agent) -> None:
    try:
        from .team import live
    except ImportError:
        return
    live.explicit_release(repo, agent.host, _session_of(agent))


@app.command()
def done(
    what: str = typer.Argument("", help="one claim (description or id); empty means all of yours"),
    everyone: bool = typer.Option(False, "--all", help="release every agent's claims in this repo (asks first)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="with --all: do not ask"),
) -> None:
    """Release your claims. Only ever your own, unless you say --all."""
    from .claims import Claims

    repo = _repo()
    me = _me(repo)
    with Claims(repo) as c:
        if everyone:
            live = c.live()
            if not live:
                out.print("Nothing is claimed here.")
                return
            others = [x for x in live if not x.held_by(me)]
            if others and not yes:
                for x in others:
                    out.print(f"  {x.label}: {', '.join(x.globs) or '(advisory)'} ({x.description})")
                if not sys.stdin.isatty() or not typer.confirm(f"Release {len(others)} claim(s) other agents hold?"):
                    raise Stop("Nothing released.", "To release them all without asking:  knos done --all --yes")
            gone = c.release(me, what, everyone=True)
        else:
            gone = c.release(me, what)
    if gone:
        _team_release(repo, me)
    if not gone:
        out.print("You hold no claims here." if not what else f"You hold no claim on {what} here.")
        out.print("[dim]This releases only your own. Every agent's:  knos done --all[/dim]")
        return
    for x in gone:
        out.print(f"Released {', '.join(x.globs) or '(advisory)'} ({x.description}, {x.label}).")


@app.command()
def status() -> None:
    """What knos holds for this repo, and who is working where."""
    from . import guard
    from .claims import Claims, claims_db

    repo = _repo()
    _fresh(repo)
    with Memory(repo) as mem:
        size = mem.footprint() / (1024 * 1024)
        tiers = mem.tiers()
        only_here = mem.only_here()
        capped, near = mem.capped, mem.near_full()
    out.print(f"[bold]{repo}[/bold]")
    trees = paths.worktrees(repo)
    if len(trees) > 1:
        out.print(f"  [dim]shared with {len(trees) - 1} other worktree(s) of this repo[/dim]")
    for name, what, how in tiers:
        out.print(f"  {name:<10} {what:<34} [dim]{how}[/dim]")
    room = f"{size:.1f} MB" + (" of Sibyl's 5 MB free tier (this repo's store plus your own Sibyl memory)" if capped
                                else " in Sibyl (your Sibyl account: no cap)")
    if near:
        room += "  - nearly full: knos compact, or knos pro buy (Sibyl Pro, uncapped, is included)"
    out.print(f"  {'':<10} {room}")
    out.print(f"  {'':<10} {only_here} notes exist nowhere else; the rest is re-read from your repo")
    if claims_db(repo).exists():
        with Claims(repo) as c:
            live = c.live()
        for x in live:
            out.print(f"  [yellow]claimed[/yellow]    {x.label}: {', '.join(x.globs) or '(advisory)'} "
                      f"({x.description}, {x.minutes_left:.0f} min left)")
    found = sessions.clients_found()
    out.print(f"  agent history: {', '.join(k for k, v in found.items() if v) or 'none found'}")
    if not code.indexed(repo):
        structure = "still to read (knos point)"
    elif code.installed():
        structure = "read, with universal-ctags"
    else:
        structure = f"read, by knos itself ({builtin_reader.languages()} kinds of file)"
    out.print(f"  code structure: {structure}")
    wired = guard.installed()
    out.print(f"  edit guard: {', '.join(k for k, v in wired.items() if v) or 'off (knos init)'}")
    out.print(f"  {len(private.DEFAULT_PATTERNS)} kinds of secret private by default, "
              f"{len(private.added_patterns(repo))} added by you")


@app.command()
def doctor() -> None:
    """What is guarded and what is not: agent hosts, the commit guard, the team key's float, quiet members."""
    from . import doctor as doc

    rows = doc.run(paths.repo_here())
    for name, ok, detail in rows:
        mark = "[green]ok[/green]" if ok else "[yellow]!![/yellow]"
        out.print(f"  {mark}  {name}: ", end="")
        _quote(detail)
    if not rows:
        out.print("No agent host found on this machine.")


@app.command()
def worth() -> None:
    """What knos has actually done here: claims, releases, edits refused."""
    from . import worth as tally

    repo = _repo()
    with Memory(repo) as mem:
        got = tally.tally(repo, mem)
    out.print(f"[bold]{repo.name}[/bold]")
    out.print(f"  {tally.sentence(got)}")
    out.print(f"  claimed    {got['claimed']:4}   by {got['agents']} agent(s); {got['live']} live now")
    out.print(f"  released   {got['released']:4}   given back rather than left to lapse")
    out.print(f"  blocked    {got['blocked']:4}   edits refused because another agent held the file")
    out.print(f"  withdrawn  {got['withdrawn']:4}   rules the instruction file stopped carrying")
    out.print("[dim]Counted from what was written at the time, not from a counter.[/dim]")


@app.command()
def stats(share: bool = typer.Option(False, "--share", help="one line to paste anywhere; counts only, no paths")) -> None:
    """What Knos did in this repo, in counts: claims, collisions refused, team claims on chain."""
    from . import worth as tally

    repo = _repo()
    got = tally.tally(repo)
    team_claims = team_refused = 0
    if (repo / ".knos" / "team.json").exists():
        try:
            from .team import live
            rt = live.runtime(repo, fetch_salt=False)
            if rt is not None:
                ev = live.events(rt)
                team_claims = sum(1 for e in ev if e["kind"] == "claim")
                team_refused = sum(1 for e in ev if e["kind"] in ("blocked", "lost"))
        except Exception:  # noqa: BLE001
            pass
    line = (f"My agents: {got['claimed'] + team_claims} claims across {max(got['agents'], 1)} agent(s), "
            f"{got['blocked'] + team_refused} conflicting edits refused before they happened"
            + (f", {team_claims} of them arbitrated on Solana" if team_claims else "")
            + " — Knos, github.com/drexthealpha/Knos")
    if share:
        _quote(line)
        return
    out.print(f"[bold]{repo.name}[/bold]")
    out.print(f"  claims {got['claimed']} local, {team_claims} on chain; refused {got['blocked']} local, "
              f"{team_refused} across machines")
    out.print("  Share it:  knos stats --share")


@app.command()
def who() -> None:
    """Which agents finish what they claim, and what hold that has earned them."""
    from . import record

    repo = _repo()
    with Memory(repo) as mem:
        everyone = record.everyone(mem)
    if not everyone:
        out.print(f"Nobody has claimed anything here yet. Every agent starts at {record.UNKNOWN} minutes.")
        return
    out.print("[bold]who[/bold]                    [dim]claimed  closed  hold[/dim]")
    for got in everyone:
        out.print(f"  {got['who'][:22]:22} {got['taken']:4}  {got['finished']:6}  {got['holds']:3} min")


# ---- Sibyl's paid features ---------------------------------------------------------------


@app.command()
def learn(accept: str = typer.Option(None, "--accept", metavar="ID", help="accept a proposal: it becomes a playbook"),
          show: bool = typer.Option(False, "--show", help="list pending proposals without a new pass")) -> None:
    """Sibyl's self-learning over this repo's journal: repeated patterns across agents become team playbooks."""
    from . import sibyl

    repo = _repo()
    try:
        with Memory(repo) as mem:
            if accept:
                try:
                    path = sibyl.accept(mem, repo, accept)
                except LookupError as why:
                    raise Stop(str(why), "See them:  knos learn --show") from None
                out.print(f"Accepted. Playbook written to {path.relative_to(repo).as_posix()}: review it and commit "
                          "it; every machine imports it at session start.")
                return
            got = sibyl.learn(mem, run=not show)
    except sibyl.NeedsPro as why:
        raise Stop(f"knos learn {why}.") from None
    if not show:
        out.print(f"Read {got['events_scanned']} journal entries; {got['proposals_made']} new proposal(s).")
    if not got["pending"]:
        out.print("No pending proposals.")
    for p in got["pending"]:
        out.print(f"  {p['id'][:12]}  {p['confidence']:.2f}  {p['title'] or p['slug']}", markup=False)
    if got["pending"]:
        out.print("Accept one:  knos learn --accept <id>")


@app.command()
def lint() -> None:
    """Sibyl's memory linter, plus a check for agents that recorded opposite things."""
    from . import sibyl

    repo = _repo()
    try:
        with Memory(repo) as mem:
            got = sibyl.lint(mem)
    except sibyl.NeedsPro as why:
        raise Stop(f"knos lint {why}.") from None
    if got["text"]:
        _quote(got["text"])
    for c in got["contradictions"]:
        _quote(f"  contradiction: {c['a_by'] or '?'} recorded {c['a']!r}; {c['b_by'] or '?'} recorded {c['b']!r}")
    out.print("Memory is healthy." if got["ok"] else "Fix these before they spread: knos forget, or record the "
              "decision that stands.")


# ---- sharing through the repo ------------------------------------------------------------


@app.command()
def export(to: str = typer.Option(None, "--to", metavar="PATH", help="write somewhere else, relative to the repo")) -> None:
    """Write decisions and current claims into the repo, to commit."""
    from . import share

    repo = _repo()
    try:
        with Memory(repo) as mem:
            target, decisions, claims = share.write(repo, mem, to)
    except ValueError as problem:
        raise Stop(str(problem), "Give a path inside the repo.") from None
    rel = target.relative_to(repo).as_posix()
    out.print(f"Wrote {rel}: {decisions} decisions, {claims} claimed. Commit it; a fresh clone reads it back.")
    if not share.read_back(repo, target):
        out.print(f"[dim]knos will not read {rel} back; it reads .knos/decisions.md, DECISIONS.md, WORKLOG.md "
                  "and docs/adr/*.md.[/dim]")


memory_app = typer.Typer(add_completion=False, help="this repo's Sibyl memory as one portable file; continuity notes")
app.add_typer(memory_app, name="memory")


@memory_app.command("export")
def memory_export(out_file: str = typer.Option(None, "--out", metavar="FILE", help="write here (default: stdout)")) -> None:
    """Every Knos/Sibyl record for this repo as versioned, sorted JSON with a sha256."""
    import json as _json

    from . import memory_io

    repo = _repo()
    with Memory(repo) as mem:
        doc = memory_io.export_doc(mem.client, repo.name)
    text = _json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if not out_file:
        sys.stdout.write(text)
        return
    Path(out_file).write_text(text, encoding="utf-8")
    out.print(f"Wrote {out_file}: {doc['count']} records, sha256 {doc['sha256'][:16]}", markup=False)
    if doc["continuity"]:
        out.print(f"Continuity: {doc['continuity']}", markup=False)


@memory_app.command("import")
def memory_import(file: str = typer.Argument(..., help="a file `knos memory export` wrote")) -> None:
    """Merge an export into this repo's memory. Safe to run twice."""
    import json as _json

    from . import memory_io

    try:
        doc = _json.loads(Path(file).read_text(encoding="utf-8"))
        with Memory(_repo()) as mem:
            written, same = memory_io.import_doc(mem.client, doc)
    except (OSError, ValueError) as problem:
        raise Stop(f"Could not import {file}: {problem}", "Give a file `knos memory export --out` wrote.") from None
    out.print(f"Imported {file}: {written} written, {same} already here.", markup=False)


@memory_app.command("note")
def memory_note(text: str = typer.Argument(..., help="what the next session here should know first")) -> None:
    """Leave the continuity note: shown at the next session start and by `knos memory export`."""
    from . import memory_io

    with Memory(_repo()) as mem:
        memory_io.note(mem.client, text)
    out.print("Continuity note kept; the next session here starts with it.")


@app.command()
def restore() -> None:
    """Rebuild this repo's decisions from the record committed to it."""
    from . import share

    repo = _repo()
    with Memory(repo) as mem:
        kept, skipped = share.restore(repo, mem)
    if kept == 0 and skipped == 0:
        out.print("Nothing to restore: no .knos/decisions.md in this repo.")
        return
    out.print(f"Restored {kept} decision(s) from .knos/decisions.md." + (f" {skipped} were already here." if skipped else ""))


# ---- showing it ------------------------------------------------------------------------------


@app.command()
def demo(fast: bool = typer.Option(False, "--fast", help="no pauses")) -> None:
    """Run the whole product on a throwaway repo. Your own repos are not touched."""
    from . import demo as demo_mod

    raise typer.Exit(demo_mod.run(out, pause=0.0 if fast else demo_mod.PAUSE))


@app.command()
def board(
    port: int = typer.Option(0, "--port", help="0 picks a free one"),
    no_open: bool = typer.Option(False, "--no-open", help="print the address, do not open a browser"),
) -> None:
    """A live page of this repo: claims, agents, spend. Loopback only, with a per-run token."""
    from . import board as board_mod

    repo = _repo()
    board_mod.serve(repo, port=port, open_browser=not no_open, say=lambda s: out.print(s, markup=False))


@app.command()
def bench(
    what: str = typer.Argument(None, help="jobs: full hire-to-payment jobs on the escrow"),
    live: bool = typer.Option(False, "--live", help="jobs: on devnet instead of the in-process runtime"),
    tempo: bool = typer.Option(False, "--tempo", help="jobs: the Tempo escrow (on a local anvil)"),
    jobs: int = typer.Option(None, "--jobs", help="jobs: how many"),
    out_file: str = typer.Option(None, "--out", help="also write the results as markdown here"),
    quick: bool = typer.Option(False, "--quick", help="fewer rounds"),
    chain: str = typer.Option(None, "--chain", metavar="URL",
                              help="also the team bars, on a local validator (scripts/devchain.sh start)"),
    rounds: int = typer.Option(200, "--rounds", help="with --chain: security rounds"),
) -> None:
    """Measure knos on this machine: collisions, friction, recall, speed. Every number is re-runnable."""
    if what == "jobs":
        import json as _json

        from .jobs import bench as jobs_bench

        try:
            got = jobs_bench.run(live=live, tempo=tempo, jobs=jobs)
        except (FileNotFoundError, NotImplementedError, LookupError) as why:
            raise Stop(str(why)) from None
        _quote(_json.dumps(got, indent=1))
        if out_file:
            Path(out_file).write_text(_json.dumps(got, indent=1), encoding="utf-8")
        return
    if what:
        raise Stop(f"Unknown bench {what!r}.", "Try:  knos bench   or   knos bench jobs")
    if chain:
        import json as _json

        from . import bench_chain

        got = bench_chain.run(chain, rounds=rounds, quick=quick, say=lambda s: out.print(s, markup=False))
        _quote(_json.dumps(got, indent=1))
        if out_file:
            Path(out_file).write_text(_json.dumps(got, indent=1), encoding="utf-8")
        return
    from . import bench as bench_mod

    raise typer.Exit(bench_mod.main(out_file, quick=quick, say=lambda s: out.print(s, markup=False)))


@app.command("mainnet-check")
def mainnet_check_cmd(
    multisig: str = typer.Option(None, "--multisig", help="the Squads v4 multisig (default: KNOS_SQUADS_MULTISIG)"),
) -> None:
    """The mainnet gates, checked on chain: Squads time-locked authority, verified build, security.txt, IDL, audit."""
    from . import mainnet_check

    raise typer.Exit(mainnet_check.main(lambda s: out.print(s, markup=False), multisig=multisig))


# ---- plumbing --------------------------------------------------------------------------------


@app.command("mcp", hidden=True)
def mcp_cmd() -> None:
    """The Knos MCP server over stdio (memory, claims, jobs, pay)."""
    from . import mcp

    mcp.main()


@app.command("hook", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def hook_cmd(ctx: typer.Context, which: str = typer.Argument(..., help="guard or start")) -> None:
    """The agent hooks. Always exit 0 or 2 (2 = refuse an edit); never crash in front of an agent."""
    try:
        if which == "guard":
            from . import guard_hook

            raise typer.Exit(guard_hook.main(list(ctx.args)))
        if which == "start":
            from . import start_hook

            raise typer.Exit(start_hook.main(list(ctx.args)))
        if which == "proof":  # Stop: no finishing while the last message claims what Knos cannot prove
            from .proof import hook as proof_hook

            raise typer.Exit(proof_hook.main_proof(list(ctx.args)))
        if which == "safety":  # PreToolUse: no overwriting unread files, no deleting outside the repo
            from .proof import hook as proof_hook

            raise typer.Exit(proof_hook.main_safety(list(ctx.args)))
        if which == "commit":  # git pre-commit / pre-push: exit 1 stops the commit
            from . import commit_guard

            args = list(ctx.args)
            stage = args[args.index("--stage") + 1] if "--stage" in args[:-1] else "commit"
            said = sys.stdin.read() if stage == "push" else ""
            repo = paths.repo_here() or Path.cwd()
            raise typer.Exit(commit_guard.run(stage, repo, said))
    except typer.Exit:
        raise
    except Exception:
        pass
    raise typer.Exit(0)


@app.command("help")
def help_cmd(command: str = typer.Argument(None, help="a command to explain")) -> None:
    """More about one command."""
    out.print(help_text.for_command(command) if command else help_text.main(), markup=False)


def _register_pro() -> None:
    try:
        from .pro.cli import register
    except ImportError:
        return
    register(app, out, Stop)


_register_pro()


def _register_team() -> None:
    try:
        from .team.cli import register
    except ImportError:  # solders or PyNaCl missing: no team commands, everything else works
        return
    register(app, out, Stop, _repo)


_register_team()


def _register_jobs() -> None:
    try:
        from .jobs.cli import register
    except ImportError:  # solders or PyNaCl missing: no jobs commands, everything else works
        return
    register(app, out, Stop)


_register_jobs()


def _register_proof() -> None:
    from .proof.cli import register
    register(app, out, Stop, _repo)


_register_proof()

# One product up front: paste an agent PR, protect a repo, fund an issue, paid on GitHub's proof. Everything else
# (claims, budgets, Pro, Tempo, ERC-8183, text jobs, the relay) is `knos labs <cmd>`; the old top-level names stay
# as hidden aliases so nothing that calls them breaks.
LABS = ("agent", "board", "budget", "claim", "done", "jobs", "pay", "pro", "report", "spend", "stats", "team",
        "verify", "who", "work", "worth")
labs = typer.Typer(add_completion=False, help="claims, budgets, Pro, Tempo, text jobs and the relay")


def _move_to_labs() -> None:
    import copy

    for info in app.registered_commands:
        name = info.name or info.callback.__name__.replace("_", "-")
        if name in LABS:
            labs.registered_commands.append(copy.copy(info))
            setattr(info, "hidden", True)
    for info in app.registered_groups:
        if info.name in LABS:
            labs.registered_groups.append(copy.copy(info))
            setattr(info, "hidden", True)
    app.add_typer(labs, name="labs")


_move_to_labs()


def main(argv: list[str] | None = None) -> int:
    """The console script. Errors are one line, never a traceback."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:2] == ["plane", "mcp"]:  # host configs written by 0.1 start `knos plane mcp`
        args = ["mcp"] + args[2:]
    try:
        rc = app(args=args, standalone_mode=False, prog_name="knos")
        return int(rc) if isinstance(rc, int) else 0
    except Stop as why:
        out.print(why.said, markup=False)
        if why.fix:
            out.print(why.fix, markup=False)
        return 1
    except StoreGone as gone:
        out.print(str(gone), markup=False)
        return 1
    except typer.Exit as e:
        return int(e.exit_code or 0)
    except typer.Abort:
        out.print("Stopped.")
        return 1
    except KeyboardInterrupt:
        out.print("Stopped.")
        return 130
    except Exception as e:  # usage errors and anything unforeseen: one line
        # A usage error from click, or from the copy of click newer typers bundle: both carry format_message().
        if hasattr(e, "format_message") and type(e).__name__.endswith(("UsageError", "BadParameter", "NoSuchOption",
                                                                       "MissingParameter", "BadOptionUsage",
                                                                       "ClickException", "BadArgumentUsage")):
            out.print(e.format_message(), markup=False)
            out.print("See:  knos help", markup=False)
            return 2
        out.print(f"knos stopped: {type(e).__name__}: {e}", markup=False)
        out.print("If this repeats, please report it with the command you ran.", markup=False)
        return 1


def _entry() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    _entry()
