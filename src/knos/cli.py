"""The knos command line.

Two commands do the work. There is no account, no key, no config file and no
join step. Every command is something a person typed; knos does nothing on
its own between them.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from . import answer, code, errors, help as help_text, link, paths, private, sessions
from .memory import TOPIC, Fact, Memory

app = typer.Typer(
    add_completion=False,
    help="one memory for every agent here, and it knows who is in your code now",
)
# Answers are quoted from other people's writing, which on Windows routinely
# contains characters the console's default code page cannot encode. Ask for
# UTF-8, and settle for replacing what will not fit rather than failing on an
# em dash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# Lines here are written to fit 80 columns already; let them, rather than
# having Rich rewrap a command someone needs to copy.
out = Console(soft_wrap=True, highlight=False)


def _quote(text: str) -> None:
    """Print something a person or an agent wrote.

    Markup is off: a commit message containing [dim] is a commit message,
    not an instruction to Rich.
    """
    out.print(text, markup=False)


@app.callback(invoke_without_command=True)
def _no_command(ctx: typer.Context) -> None:
    """Typing `knos` on its own shows the one screen, not a usage box."""
    if ctx.invoked_subcommand is None:
        out.print(help_text.main())


def _stop(problem: errors.Problem) -> None:
    out.print(problem.said)
    out.print(problem.fix)
    raise typer.Exit(1)


def _repo(given: str | None) -> Path:
    if given:
        return Path(given).resolve()
    current = paths.current_repo()
    if current is None:
        _stop(errors.nothing_indexed())
    return current  # type: ignore[return-value]


@app.command()
def point(path: str = typer.Argument(".", help="the repo to read")) -> None:
    """Read this repo."""
    repo = Path(path).resolve()
    if not repo.is_dir():
        _stop(errors.no_such_folder(path))

    # Reading a repo replaces what knos knew about it, rather than adding to
    # it. Run this again whenever you want it to catch up: twice in a row is
    # the same as once, which is the only behaviour that is not a trap.
    try:
        paths.store_for(repo).unlink(missing_ok=True)
    except OSError:
        # Windows will not delete a file another process still has open,
        # which here means a second knos is reading this repo right now.
        _stop(errors.busy(repo))

    started = time.perf_counter()

    def progress(note: str) -> None:
        # Live, on one line, so a long read looks like work rather than a
        # hang. Anything already read stays read if this is interrupted.
        out.print(f"  {note}...", end="\r", highlight=False)

    with Memory(repo) as mem:
        counts = answer.point(repo, mem, on_progress=progress)
    paths.remember_pointed(repo)
    took = time.perf_counter() - started

    out.print(" " * 60, end="\r")
    out.print(f"Read {repo.name} in {took:.0f}s.")
    out.print(f"  {counts['sessions']} things said in past agent sessions")
    out.print(f"  {counts['commits']} commits")
    if counts["code"]:
        out.print(f"  {counts['code']} pieces of code structure")
    if counts["private"]:
        out.print(f"  {counts['private']} private, kept from your agents")

    if not code.installed():
        out.print("")
        out.print(str(errors.code_engine_missing()))

    skipped = errors.report_skipped(counts.get("skipped") or [])
    if skipped:
        out.print(skipped)
    if counts.get("full"):
        out.print("")
        out.print(str(errors.memory_full(repo)))
    if not counts["commits"] and not counts["code"]:
        out.print("")
        out.print(str(errors.not_a_repo(str(repo))))
    out.print("")
    out.print('Ask it something:  knos ask "what did we decide about auth?"')


@app.command()
def ask(
    question: str = typer.Argument(..., help="what you want to know"),
    path: str = typer.Option(None, "--in", help="the repo to ask about"),
) -> None:
    """Ask about it."""
    repo = _repo(path)
    started = time.perf_counter()
    with Memory(repo) as mem:
        found = answer.ask(repo, mem, question)
        joined = link.cross(repo, found)
    took = (time.perf_counter() - started) * 1000

    if not found:
        _stop(errors.nothing_found(repo))

    for hop in joined:
        _quote(hop.text)
        out.print(f"    [dim]{hop.where}[/dim]")
        out.print("")

    shown = {h.decision.text for h in joined}
    for p in found:
        if p.text in shown:
            continue
        text = p.text.strip().replace("\r", "")
        if len(text) > 400:
            text = text[:400].rsplit(" ", 1)[0] + "..."
        _quote(text)
        out.print(f"    [dim]{p.where}[/dim]")
        out.print("")
    out.print(f"[dim]{len(found)} found in {took:.0f}ms[/dim]")

    # Said here rather than only after `point`, because this is the question
    # where a missing code reader is actually felt.
    if not code.installed() and answer.looks_structural(question):
        out.print("")
        out.print(str(errors.code_engine_missing()))


@app.command()
def connect(
    write: bool = typer.Option(
        False, "--write", help="add knos to the configs it finds, and back them up"
    ),
) -> None:
    """Let your agents use it."""
    exe = Path(sys.executable).as_posix()
    if write:
        _write_configs(exe)
        return
    entry = (
        '"knos": {\n'
        f'  "command": "{exe}",\n'
        '  "args": ["-m", "knos.mcp"]\n'
        '}'
    )

    out.print("Claude Code")
    out.print(f"  claude mcp add knos -- {exe} -m knos.mcp")
    out.print("")

    for name, where in _config_files():
        out.print(name)
        out.print(f"  {where}")
        out.print("")
    out.print('  Add this inside "mcpServers":')
    out.print("")
    for line in entry.splitlines():
        out.print(f"    {line}")
    out.print("")
    out.print("Restart the agent. You should see four tools: search, about,")
    out.print("remember, sources. Then ask it something you only told the other one.")


def _write_configs(exe: str) -> None:
    """Add knos to each agent's settings, keeping a copy of what was there.

    Editing somebody's editor settings without being asked would be rude,
    which is why this is a flag and not the default. Being asked and then
    making them paste JSON by hand would just be unhelpful.
    """
    import json

    entry = {"command": exe, "args": ["-m", "knos.mcp"]}
    touched = False
    for name, where in _config_files():
        path = Path(where)
        if not path.parent.is_dir():
            out.print(f"{name} is not installed here, so nothing to do.")
            continue
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (ValueError, OSError):
            out.print(f"{name}: {path} is not readable, so knos left it alone.")
            out.print("  Add it by hand:  knos connect")
            continue

        servers = existing.setdefault("mcpServers", {})
        if servers.get("knos") == entry:
            out.print(f"{name} already has it.")
            continue
        if path.exists():
            backup = path.with_suffix(path.suffix + ".before-knos")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            out.print(f"{name}: kept a copy at {backup.name}")
        servers["knos"] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        out.print(f"{name}: added.")
        touched = True

    out.print("")
    if touched:
        out.print("Restart them. You should see four tools: search, about,")
        out.print("remember, sources.")
    else:
        out.print("Nothing changed.")


def _config_files() -> list[tuple[str, str]]:
    """Where each client keeps its settings, on this machine.

    Printed rather than written: these are the person's own editor settings,
    and a tool that edits them behind your back is worse than one that tells
    you the path.
    """
    home = Path.home()
    if sys.platform == "darwin":
        desktop = home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif sys.platform.startswith("win"):
        import os

        roaming = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        desktop = roaming / "Claude" / "claude_desktop_config.json"
    else:
        desktop = home / ".config/Claude/claude_desktop_config.json"
    return [
        ("Claude Desktop", desktop.as_posix()),
        ("Cursor", (home / ".cursor" / "mcp.json").as_posix()),
    ]


@app.command()
def status() -> None:
    """What it has read."""
    repo = paths.current_repo()
    if repo is None:
        _stop(errors.nothing_indexed())
    with Memory(repo) as mem:
        size = mem.size_mb()
        tiers = mem.tiers()
        yielded = mem.coordination()
        claimed = mem.claimed_now()
    found = sessions.clients_found()
    out.print(f"Reading {repo}")
    for name, what, how in tiers:
        out.print(f"  {name:<10} {what:<34} [dim]{how}[/dim]")
    for line in claimed:
        out.print(f"  {'':<10} [dim]{line}[/dim]")
    out.print(f"  {'':<10} {size:.1f} MB of 5 MB used")
    if yielded:
        out.print("")
        out.print("  who stood down for whom, while a claim was live")
        for line in yielded:
            out.print(f"    [dim]{line}[/dim]")
    out.print(f"  agent history: {', '.join(k for k, v in found.items() if v) or 'none found'}")
    if not code.installed():
        structure = "not installed"
    else:
        structure = "yes" if code.indexed(repo) else "still to read"
    out.print(f"  code structure: {structure}")
    kept = len(private.added_patterns(repo))
    out.print(
        f"  {len(private.DEFAULT_PATTERNS)} kinds of secret private by default,"
        f" {kept} added by you"
    )


@app.command("private")
def private_cmd(path: str = typer.Argument(..., help="a path to keep private")) -> None:
    """Keep a path from your agents."""
    repo = _repo(None)
    private.add(repo, path)
    out.print(f"{path} is private.")
    out.print("You can still search it. Your agents cannot see it.")


@app.command()
def share(
    path: str = typer.Argument(..., help="the folder to share"),
    with_: str = typer.Option(..., "--with", help="who to share it with"),
) -> None:
    """Let a teammate's agent read a folder."""
    from . import team

    try:
        team.share(path, with_)
    except team.NotSetUp as why:
        out.print(f"Cannot share {path} yet.")
        out.print(f"  {why}")
        raise typer.Exit(1)
    out.print(f"{with_} can read {path}.")
    out.print(f"Stop them later:  knos unshare {path} --with {with_}")


@app.command()
def unshare(
    path: str = typer.Argument(..., help="the folder to stop sharing"),
    with_: str = typer.Option(..., "--with", help="who to stop"),
) -> None:
    """Stop a teammate's agent reading a folder."""
    from . import team

    try:
        team.unshare(path, with_)
    except team.NotSetUp as why:
        out.print(f"Cannot change {path} yet.")
        out.print(f"  {why}")
        raise typer.Exit(1)
    out.print(f"{with_} can no longer read {path}.")


@app.command()
def remember(
    fact: str = typer.Argument(..., help="something your agents should know"),
    about: str = typer.Option(None, "--about", help="what to file it under"),
) -> None:
    """Tell your agents something."""
    from datetime import datetime, timezone

    repo = _repo(None)
    now = datetime.now(timezone.utc).isoformat()
    name = about or answer.topic_of(fact)
    with Memory(repo) as mem:
        mem.record(
            Fact(
                text=fact,
                source="note",
                where=f"you said so, {now[:10]}",
                when=now,
                about=name,
            )
        )
        mem.note_thing(TOPIC, name, {"note": fact, "when": now[:10]})
    out.print(f"Noted, under {name}.")
    out.print(f"Every agent you connect will know. Drop it:  knos forget {name}")


@app.command()
def done() -> None:
    """Say you have finished what you were doing."""
    repo = _repo(None)
    with Memory(repo) as mem:
        mem.done_working()
    out.print("Noted. Your other agents will stop being warned off it.")


@app.command()
def notes() -> None:
    """What your agents have written down."""
    repo = _repo(None)
    with Memory(repo) as mem:
        written = mem.notes()
    if not written:
        out.print("Nothing written down yet.")
        out.print('Your agents add to this with their remember tool, or:')
        out.print('  knos ask "..."   to see what is already known')
        return
    for n in written:
        _quote(f"{n['about']}: {n['note']}")
        out.print(f"    [dim]{n['when']}[/dim]")
        out.print("")
    out.print(f"[dim]{len(written)} written down. Drop one: knos forget <name>[/dim]")


@app.command()
def forget(about: str = typer.Argument(..., help="the note to drop")) -> None:
    """Drop something your agents wrote down."""
    repo = _repo(None)
    with Memory(repo) as mem:
        if not mem.remembered(about):
            out.print(f"Nothing written down about {about}.")
            out.print("See what there is:  knos notes")
            raise typer.Exit(1)
        mem.supersede(TOPIC, about, "the person dropped it")
    out.print(f"Forgotten: {about}.")
    out.print("Your agents will not repeat it.")


@app.command("help")
def help_cmd(command: str = typer.Argument(None, help="a command to explain")) -> None:
    """More about one command."""
    out.print(help_text.for_command(command) if command else help_text.main())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
