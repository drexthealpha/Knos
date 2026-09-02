"""The knos command line.

Two commands do the work. There is no account, no key, no config file and no
join step. Every command is something a person typed; knos does nothing on
its own between them.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

from . import answer, builtin_reader, code, errors, help as help_text, link, paths, private, sessions
from .memory import TOPIC, Fact, Memory

app = typer.Typer(
    add_completion=False,
    help="one local memory every coding agent here shares, and it knows who is in your code now",
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


def _read(repo: Path, code_budget: float | None = None) -> tuple[dict, float]:
    """Read a repo, showing progress. The one place that does it."""
    started = time.perf_counter()

    def progress(note: str) -> None:
        # Live, on one line, so a long read looks like work rather than a
        # hang. Anything already read stays read if this is interrupted.
        out.print(f"  {note}...", end="\r", highlight=False)

    with Memory(repo) as mem:
        counts = answer.point(
            repo, mem, on_progress=progress, code_budget=code_budget
        )
    paths.remember_pointed(repo)
    out.print(" " * 60, end="\r")
    return counts, time.perf_counter() - started


def _repo(given: str | None) -> Path:
    if given:
        return Path(given).resolve()

    # Reading a repo was a step you had to know about before knos would say
    # anything, which put a command and a concept between install and the
    # first answer. It is the same work either way, so knos does it and says
    # so, rather than sending you away to type it yourself.
    here = paths.repo_here()
    if here is not None and not paths.has_store(here):
        out.print(f"[dim]First time in {here.name}. Reading it now.[/dim]")
        _read(here, code_budget=code.CODE_BUDGET)
        return here

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

    counts, took = _read(repo)
    out.print(f"Read {repo.name} in {took:.0f}s.")
    if counts.get("rules"):
        out.print(f"  {counts['rules']} rules written down in this repo")
    out.print(f"  {counts['sessions']} things said in past agent sessions")
    out.print(f"  {counts['commits']} commits")
    if counts["code"]:
        out.print(f"  {counts['code']} pieces of code structure")
    if counts["private"]:
        out.print(f"  {counts['private']} private, kept from your agents")

    skipped = errors.report_skipped(counts.get("skipped") or [])
    if skipped:
        out.print(skipped)
    if counts.get("full"):
        out.print("")
        out.print(str(errors.memory_full(repo, counts["sessions"] + counts["commits"])))
    if not counts["commits"] and not counts["code"]:
        out.print("")
        out.print(str(errors.not_a_repo(str(repo))))
    out.print("")
    if _already_connected():
        out.print('Ask it something:  knos ask "what did we decide about auth?"')
    else:
        out.print("Give your agents this memory:  knos connect")


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
        # The person asking is the one who can actually resolve a collision,
        # and until now they only saw it afterwards in `knos status`.
        live = [
            w
            for w in mem.claims()
            if answer.same_subject(str(w.get("topic", "")), question)
        ]
    took = (time.perf_counter() - started) * 1000

    for work in live:
        holder = str(work.get("who") or "Another agent")
        started = "You are" if holder == "you" else f"{holder} is"
        out.print(f"[yellow]{started} working on {work.get('topic')} right now.[/yellow]")
    if live:
        out.print("")

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
    if answer.looks_structural(question) and not code.indexed(repo):
        out.print("")
        out.print(str(errors.structure_unread(repo)))


@app.command()
def connect(
    show: bool = typer.Option(
        False, "--print", help="just show what to paste, and change nothing"
    ),
) -> None:
    """Let your agents use it."""
    exe = Path(sys.executable).as_posix()
    if not show:
        # Adding it was behind a flag, and the flag was the last step people
        # did not take. It is what the command is for, every file it touches
        # is copied first, and --print is there for anyone who would rather
        # do it by hand.
        _write_configs(exe)
        return
    entry = (
        '"knos": {\n'
        f'  "command": "{exe}",\n'
        '  "args": ["-m", "knos.mcp"]\n'
        '}'
    )

    for name, where in _config_files():
        out.print(name)
        out.print(f"  {where}")
        out.print("")
    out.print('  Add this inside "mcpServers":')
    out.print("")
    for line in entry.splitlines():
        out.print(f"    {line}")
    out.print("")
    out.print("Restart the agent. You should see three tools: search, about,")
    out.print("and remember. Then ask it something you only told the other one.")
    out.print("")
    out.print("Or let knos do it, keeping a copy of each file:  knos connect")


def _already_connected() -> bool:
    """Whether any agent on this machine has been pointed at knos."""
    import json

    for _, where in _config_files():
        try:
            existing = json.loads(Path(where).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if "knos" in (existing.get("mcpServers") or {}):
            return True
        if "knos" in (existing.get("mcp") or {}):
            return True
    return False


def _claude_cli() -> str | None:
    """Claude Code's own command line, if it is on this machine."""
    import shutil

    return shutil.which("claude")


def _add_via_claude_cli(exe: str) -> bool:
    """Ask Claude Code to add knos itself.

    Writing ~/.claude.json by hand works, but a session already running has
    read that file and will not read it again, so the person has to restart.
    `claude mcp add` registers the server with the running session and its
    tools are usable straight away. Same file, no restart.
    """
    import subprocess

    tool = _claude_cli()
    if tool is None:
        return False
    try:
        done = subprocess.run(
            [tool, "mcp", "add", "--scope", "user", "knos", "--", exe, "-m", "knos.mcp"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        # Already registered is a success, not a failure.
        return "already exists" in (done.stdout + done.stderr).lower()
    return True


def _write_configs(exe: str) -> None:
    """Add knos to each agent's settings, keeping a copy of what was there.

    Editing somebody's editor settings without being asked would be rude,
    which is why this is a flag and not the default. Being asked and then
    making them paste JSON by hand would just be unhelpful.
    """
    import json

    entry = {"command": exe, "args": ["-m", "knos.mcp"]}
    touched = False
    live = _add_via_claude_cli(exe)  # Claude Code, without a restart
    added: list[str] = []
    for name, where in _config_files():
        if name == "Claude Code" and live:
            continue  # done already, and usable already
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

        # OpenCode names the key `mcp`, marks a stdio server `"type": "local"`
        # and takes the command as one array rather than a command plus args.
        # Same server, written the way each client reads it.
        if name == "OpenCode":
            servers = existing.setdefault("mcp", {})
            mine = {"type": "local", "command": [exe, "-m", "knos.mcp"], "enabled": True}
            existing.setdefault("$schema", "https://opencode.ai/config.json")
        else:
            servers = existing.setdefault("mcpServers", {})
            mine = entry
        if servers.get("knos") == mine:
            out.print(f"{name} already has it.")
            continue
        if path.exists():
            backup = path.with_suffix(path.suffix + ".before-knos")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        if not isinstance(existing, dict):
            out.print(f"{name}: {path} is not what knos expected, so it left it alone.")
            continue
        servers["knos"] = mine
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        added.append(name)
        touched = True

    if live:
        out.print("Added to Claude Code. Its tools work in the session you are in")
        out.print("already; there is nothing to restart.")
    for name in added:
        # One sentence, naming the app, because that is the whole remaining
        # step and a vague "restart your agents" makes people guess which.
        out.print(f"Added to {name}. Restart {name}.")
    if live or touched:
        out.print("")
        # "That is all" was a dead end: installed, and nothing to do with it.
        # This is the shortest path from here to the one thing knos does that
        # a file cannot.
        out.print("To see what you just gained:")
        out.print('  knos claim "the parser"    your agents are refused, and')
        out.print("                             you see the words they get")
        out.print("  knos done                  give it back")
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
    opencode = os.environ.get("OPENCODE_CONFIG")
    if opencode:
        oc = Path(opencode)
    elif sys.platform.startswith("win"):
        oc = Path(os.environ.get("PROGRAMDATA", home)) / "opencode" / "opencode.json"
    else:
        oc = home / ".config" / "opencode" / "opencode.json"
    return [
        # Claude Code keeps user-scoped servers at the top level of this
        # file. It was the one client knos told you to wire by hand, which
        # is the client most people are actually using.
        ("Claude Code", (home / ".claude.json").as_posix()),
        ("Claude Desktop", desktop.as_posix()),
        ("Cursor", (home / ".cursor" / "mcp.json").as_posix()),
        ("OpenCode", oc.as_posix()),
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
        only_here = mem.only_here()
    found = sessions.clients_found()
    out.print(f"Reading {repo}")
    trees = paths.worktrees(repo)
    if len(trees) > 1:
        # Worktrees keep files apart on purpose. There is no reason for them
        # to keep what was decided apart too, so they do not.
        out.print(f"  {'':<10} [dim]shared with {len(trees) - 1} other"
                  f" worktree{'s' if len(trees) > 2 else ''} of this repo[/dim]")
    for name, what, how in tiers:
        out.print(f"  {name:<10} {what:<34} [dim]{how}[/dim]")
    for line in claimed:
        out.print(f"  {'':<10} [dim]{line}[/dim]")
    room = f"{size:.1f} MB of 5 MB used"
    if size >= 4.0:
        room += "  - nearly full; the oldest will stop being read"
    out.print(f"  {'':<10} {room}")
    out.print(
        f"  {'':<10} [bold]{only_here} of them exist nowhere else[/bold]"
        " - told, claimed, stood down"
    )
    out.print(
        f"  {'':<10} [dim]delete the store and only those go;"
        " the rest is re-read from your repo[/dim]"
    )
    if yielded:
        out.print("")
        out.print("  who stood down for whom, while a claim was live")
        for line in yielded:
            out.print(f"    [dim]{line}[/dim]")
    out.print(f"  agent history: {', '.join(k for k, v in found.items() if v) or 'none found'}")
    if not code.indexed(repo):
        structure = "still to read"
    elif code.installed():
        structure = "read, with universal-ctags"
    else:
        structure = f"read, by knos itself ({builtin_reader.languages()} kinds of file)"
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
def claim(
    topic: str = typer.Argument(..., help="what you are about to work on"),
    who: str = typer.Option("you", "--as", help="the name to claim it under"),
) -> None:
    """Say you are working on something, so your agents hold off."""
    from datetime import datetime, timezone

    repo = _repo(None)
    now = datetime.now(timezone.utc).isoformat()
    with Memory(repo) as mem:
        # No session id: a person is not a connection, and a claim made at
        # the terminal has to outlive the shell that made it. `knos done`
        # is how it ends, along with the thirty minutes every claim gets.
        mem.working_on(topic, who, now)
    out.print(f"Claimed {topic}. Every agent here now gets this, and nothing else:")
    out.print("")
    for line in answer.withheld(topic, who == "you").splitlines():
        out.print(f"  [dim]{line}[/dim]" if line else "")
    out.print("")
    out.print("Give it back with:  knos done")


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
