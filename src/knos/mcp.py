"""The MCP server. Local stdio, launched by the client. Nothing hosted.

Every tool here answers a request an agent made on a person's behalf. The
server holds no timer and starts no work of its own.

Callers reach knos as an agent, never as the owner, so private paths are
invisible: not redacted, not counted, simply absent.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _installed_version
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from . import answer, code, git, paths, private
from .memory import TOPIC, Fact, Memory, _minutes_since


def _version() -> str:
    """The installed version, so a client is never told the empty string.

    Read from package metadata rather than repeated here, because a second
    copy of the number is a second thing to forget to bump.
    """
    try:
        return _installed_version("knos")
    except PackageNotFoundError:  # running from a source tree, not installed
        return "0+unknown"


server = MCPServer("knos", version=_version(), instructions=(
    "One local memory every coding agent on this machine shares - and it "
    "knows which of them is in your code right now.\n\n"
    "What past sessions decided, what commits changed, what this repo's "
    "CLAUDE.md and AGENTS.md actually say, and how the code is structured. "
    "Search it before asking the person to repeat themselves.\n\n"
    "Other agents share this memory right now. One rule: before you change "
    "anything, call remember(fact, about, claiming=true). One call, and no "
    "other agent will rewrite it underneath you. It lapses on its own after "
    "half an hour.\n\n"
    "Work another agent has claimed is withheld from you: you are told who "
    "holds it, not what knos knows about it. Ask them, or pick up something "
    "else. If you genuinely must have it, call again with override set to "
    "your reason — you will get the answer, and the reason is written into "
    "the journal under your name where the person can read it."
))


NOT_POINTED = (
    "knos is not in a git repo here, so there is nothing to read."
    "  Ask the person to run knos in their project."
)
NOTHING_SHARED = "Nothing shared with you."


def _repo() -> Path | None:
    """The repo to answer from, read on the spot if it never has been.

    Telling an agent to go and ask its person to run a command is the end of
    that conversation: the agent says it, the person does not see it, and
    knos looks broken on the one call that was supposed to show what it is
    for. The read is the same work `knos point` does, it happens once, and
    the agent simply waits for it.

    A tool that cannot answer says so in words. It never raises, because a
    stack trace in an agent's transcript is not something a person can act
    on.
    """
    here = paths.repo_here()
    if here is not None and not paths.has_store(here):
        try:
            with Memory(here) as mem:
                # The code reader gets a few seconds and no more: it takes
                # two minutes on a repo the size of the kernel, and an
                # agent's first question cannot wait that long. Most projects
                # finish well inside it. When one does not, every structural
                # reply says so, and `knos point` reads it properly.
                answer.point(here, mem, code_budget=code.CODE_BUDGET)
            paths.remember_pointed(here)
        except Exception:
            # A repo knos cannot read is not a reason to fail the tool call.
            # Fall through: the pointer may still have something to answer.
            pass
        else:
            return here
    return paths.current_repo()


@server.tool(
    annotations=ToolAnnotations(
        title="Search memory",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def search(
    query: str,
    limit: int = 8,
    on_behalf_of: str = "",
    override: str = "",
    ctx: Context | None = None,
) -> str:
    """Search this machine's memory of the repo across all of it: past agent
    sessions, commits and code structure. Reads only; writes nothing except
    an override reason. Every result names where it came from.

    Work another agent has claimed is withheld: you get who holds it, not
    the answer. Ask them, or pick up something else. If you genuinely must
    have it, call again with `override` set to your reason, which is
    recorded in the journal against your name.

    `on_behalf_of` names a teammate when the agent is working for one. They
    see only the folders they were actually shared, and nothing else."""
    repo = _repo()
    if repo is None:
        return NOT_POINTED

    identity, allowed = private.AGENT, None
    if on_behalf_of:
        identity, allowed = private.GUEST, _shared_with(repo, on_behalf_of)
        if not allowed:
            return NOTHING_SHARED

    who = _who(ctx)
    with Memory(repo) as mem:
        held = _held(mem, query, who, override)
        if held:
            return held
        if override:
            _took_it_anyway(mem, query, who, override)
        found = answer.ask(
            repo, mem, query, identity=identity, limit=limit, allowed=allowed
        )
        # Search is the tool an agent reaches for constantly, so this is
        # where knowing somebody else is mid-change actually changes what it
        # does. Read from the store already open, not a second one.
        busy = _being_worked_on(mem, query, asker=who)

    if found:
        answered = "\n\n".join(f"{p.text.strip()}\n    source: {p.where}" for p in found)
    else:
        answered = "Nothing known about that."
    answered = f"{busy}\n\n{answered}" if busy else answered
    # Said on the empty answer too, and especially there: a structural
    # question that finds nothing on a large repo is the moment the person
    # most needs to know which source has not been read.
    if answer.looks_structural(query) and not code.indexed(repo):
        answered += (
            "\n\n(Knos has not read this repo's code structure - it is large"
            " enough to need `knos point .` once. Sessions, commits and"
            " instruction files are all that answered this.)"
        )
    return answered


@server.tool(
    annotations=ToolAnnotations(
        title="Look up one thing",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def about(thing: str, ctx: Context | None = None) -> str:
    """Look up everything known about one named thing: a file, a person, a
    topic. Reads only, writes nothing, and touches no network. Use `search`
    instead when the question spans more than one thing."""
    repo = _repo()
    if repo is None:
        return NOT_POINTED
    with Memory(repo) as mem:
        known = []
        for category in ("file", "person", "topic", "symbol"):
            record = mem.thing(category, thing)
            if not record:
                continue
            body = record.get("body") or {}
            said = body.get("note") or body.get("last_commit") or ""
            when = body.get("when") or body.get("last_seen") or ""
            known.append(
                f"{said}\n    source: written down, {when}"
                if said
                else f"{category}: {thing}"
            )
        found = answer.ask(repo, mem, thing, identity=private.AGENT, limit=5)
        busy = _being_worked_on(mem, thing, asker=_who(ctx))
    # The canonical record and the journal line say the same thing about a
    # written-down fact, by design. Say it once, and prefer the journal's
    # version because it names which agent said it.
    said = {p.text.strip() for p in found}
    lines = [k for k in known if k.split("\n")[0] not in said]
    lines += [f"{p.text.strip()}\n    source: {p.where}" for p in found]
    if busy:
        lines.insert(0, busy)
    return "\n\n".join(lines) if lines else f"Nothing known about {thing}."


def _held(mem: Memory, thing: str, asker: str, override: str) -> str:
    """What knos refuses to answer, and what would unlock it.

    This is the one thing knos actually controls. It cannot stop an agent
    editing a file — it has no authority over an editor. It does own what it
    knows, so on work somebody else has claimed it declines to be the source
    and says who to ask.

    Yielding is the quiet path and costs nothing. Taking the work anyway
    needs a reason, and the reason goes in the journal under the agent's own
    name, which is what makes the rule real rather than polite.
    """
    blocked = []
    for work in mem.claims():
        topic = str(work.get("topic", ""))
        holder = str(work.get("who", "")) or "another agent"
        if not _same_subject(topic, thing) or _is_holder(work, asker):
            continue
        if override or mem.overridden(topic, asker):
            continue
        blocked.append((topic, holder))

    if not blocked:
        return ""
    for topic, holder in blocked:
        mem.stood_down(topic, asker, holder, _stamp())

    # A person can claim work at the terminal, and then the agent being told
    # to hold off is talking to the very person who holds it. "Ask them" is
    # the wrong thing to say to somebody's only agent.
    by_the_person = all(h == "you" for _, h in blocked)
    if by_the_person:
        held = "; ".join(t for t, _ in blocked)
    else:
        held = "; ".join(f"{t} (held by {h})" for t, h in blocked)
    return answer.withheld(held, by_the_person)


def _is_holder(work: dict, asker: str) -> bool:
    """Whether the caller is the agent that made this claim.

    Both the name it gave and the connection it made it on. A claim written
    before sessions were recorded has none, so it falls back to the name and
    is no weaker than it was.
    """
    held_by = str(work.get("who", ""))
    session = str(work.get("session", ""))
    if session:
        return held_by == asker and session == _session()
    return held_by == asker


def _took_it_anyway(mem: Memory, thing: str, who: str, why: str) -> None:
    """Write down that an agent forced its way past every claim it hit."""
    for work in mem.claims():
        topic = str(work.get("topic", ""))
        holder = str(work.get("who", "")) or "another agent"
        if _same_subject(topic, thing) and not _is_holder(work, who):
            mem.overrode(topic, who, holder, why, _stamp())


def _being_worked_on(mem: Memory, thing: str, asker: str = "") -> str:
    """Read the live claim, and write down that this agent yielded to it.

    Two writers, one store, and neither agent ever calls the other. The
    first puts what it is doing into hot state; the second reads it, is told
    to hold off, and records that it stood down. Afterwards the journal
    shows who yielded to whom, which is the part a notice board alone does
    not give you.

    Takes the caller's open store rather than opening its own: this runs on
    every search, and opening a second connection per question was a cost
    nobody asked for.
    """
    said = []
    for work in mem.claims():
        topic = str(work.get("topic", ""))
        if not _same_subject(topic, thing):
            continue
        claimed_by = str(work.get("who", "")) or "Another agent"
        if asker and not _is_holder(work, asker):
            mem.stood_down(topic, asker, claimed_by, _stamp())
        ago = _minutes_since(str(work.get("when", "")))
        when = "just now" if ago < 2 else f"{int(ago)} minutes ago"
        said.append(
            f"{claimed_by} started working on {topic} {when}."
            " Ask them before you change it, or work on something else."
        )
    return "\n".join(said)


_same_subject = answer.same_subject
_stem = answer.stem


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _session() -> str:
    """This server process, which is one client's connection and no other.

    A client tells knos its own name and can tell it anything, so the name
    alone cannot decide who holds a claim: an agent that calls itself
    "Claude Code" would walk straight past the block. Every client spawns
    its own knos over its own pipe, so the process is something the claimer
    holds and a different client cannot borrow.
    """
    import os

    return str(os.getpid())


def _who(ctx: Context | None) -> str:
    """Which agent is asking, if it said.

    Clients name themselves when they connect. Using that means a fact
    written by one agent and read by another carries the same kind of
    source as a commit does, instead of an anonymous note.
    """
    if ctx is None:
        return "an agent"
    try:
        info = ctx.request_context.session.client_params.client_info
        return (info.name or "").strip() or "an agent"
    except Exception:
        return "an agent"


@server.tool(
    annotations=ToolAnnotations(
        title="Write to memory",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    )
)
def remember(
    fact: str, about: str, claiming: bool = False, ctx: Context | None = None
) -> str:
    """Write something back, so the next session in any agent knows it too.
    Appends; it never edits or deletes an existing memory, and there is no
    tool that does.

    Set `claiming` when you are about to start work on this, rather than
    just noting something. Other agents are then told you have it and knos
    withholds it from them until you finish or half an hour passes. Writing
    a plain fact claims nothing: a note everybody can read is the point."""
    repo = _repo()
    if repo is None:
        return NOT_POINTED
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    who = _who(ctx)
    where = f"{who} said so, {now[:10]}"
    with Memory(repo) as mem:
        mem.record(Fact(text=fact, source="note", where=where, when=now, about=about))
        mem.note_thing(TOPIC, about, {"note": fact, "when": now[:10]})
        # Only when the agent says it is starting work. A note is for
        # everybody to read; claiming it would withhold the very thing that
        # was just written down.
        if claiming:
            mem.working_on(about, who, now, session=_session())
    return f"Remembered, about {about}."


def _shared_with(repo: Path, reader: str) -> list[str]:
    """Which of this repo's folders that person may read, right now.

    Asked fresh every time, so revoking takes effect on the next question
    rather than whenever something happens to expire.
    """
    from . import team

    try:
        me = team.identity().address
        who = team.resolve(reader)
        return [f for f in _shared_folders(repo) if team.may_read(me, f, who)]
    except Exception:
        return []


def _shared_folders(repo: Path) -> list[str]:
    """Top-level folders in this repo, which are what people share."""
    return [
        d.name
        for d in sorted(repo.iterdir())
        if d.is_dir() and not d.name.startswith(".") and not private.is_private(repo, d.name)
    ]


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
