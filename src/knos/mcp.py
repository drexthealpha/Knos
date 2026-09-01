"""The MCP server. Local stdio, launched by the client. Nothing hosted.

Every tool here answers a request an agent made on a person's behalf. The
server holds no timer and starts no work of its own.

Callers reach knos as an agent, never as the owner, so private paths are
invisible: not redacted, not counted, simply absent.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer

from . import answer, git, paths, private
from .memory import TOPIC, Fact, Memory, _minutes_since

server = MCPServer("knos", instructions=(
    "Shared memory for this machine: what past agent sessions decided, what "
    "commits changed, and how the code is structured. Search it before "
    "asking the person to repeat themselves.\n\n"
    "Other agents are using this same memory right now. Before you start a "
    "piece of work, call remember to say what you are about to do, so they "
    "are told.\n\n"
    "Work another agent has claimed is withheld from you: you are told who "
    "holds it, not what knos knows about it. Ask them, or pick up something "
    "else. If you genuinely must have it, call again with override set to "
    "your reason — you will get the answer, and the reason is written into "
    "the journal under your name where the person can read it."
))


NOT_POINTED = "knos has not read a repo yet. Run:  knos point ."
NOTHING_SHARED = "Nothing shared with you."


def _repo() -> Path | None:
    """The repo knos was last pointed at, or None.

    A tool that cannot answer says so in words. It never raises, because a
    stack trace in an agent's transcript is not something a person can act
    on.
    """
    return paths.current_repo()


@server.tool()
def search(
    query: str,
    limit: int = 8,
    on_behalf_of: str = "",
    override: str = "",
    ctx: Context | None = None,
) -> str:
    """Search this machine's memory of the repo: past agent sessions, commits
    and code structure. Every result names where it came from.

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

    if not found:
        nothing = "Nothing known about that."
        return f"{busy}\n\n{nothing}" if busy else nothing
    answered = "\n\n".join(f"{p.text.strip()}\n    source: {p.where}" for p in found)
    return f"{busy}\n\n{answered}" if busy else answered


@server.tool()
def about(thing: str, ctx: Context | None = None) -> str:
    """What is known about one thing: a file, a person, a topic."""
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
    held = "; ".join(f"{t} (held by {h})" for t, h in blocked)
    for topic, holder in blocked:
        mem.stood_down(topic, asker, holder, _stamp())
    return (
        f"Withheld. {held} is being worked on right now, so knos is not the"
        " place you find out about it. Ask them, or work on something else."
        "\n\nIf you must have it anyway, call this again with"
        ' override="your reason". That is recorded against your name.'
    )


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


def _same_subject(topic: str, question: str) -> bool:
    """Whether a claim and a question are about the same thing.

    Shared word stems, not shared substrings. Substrings made a claim on a
    short word warn about half the repo: "guard" fired on "safeguarding".
    Bare word overlap fixed that but missed the obvious, because a claim on
    "parser" said nothing about "parsing".
    """
    claimed = {_stem(w) for w in answer.terms(topic)}
    asked = {_stem(w) for w in answer.terms(question)}
    return bool(claimed) and bool(claimed & asked)


# Enough English to see that parser, parsers, parsing and parsed are one
# word. Anything more wants a real stemmer, and a real stemmer is a
# dependency knos does not need to warn one agent off another's work.
_ENDINGS = ("ings", "ing", "ers", "er", "ed", "es", "s")

# Words the suffix rules cannot reach, because English does not spell them
# the way it spells everything else. Short on purpose: this list exists to
# match a claim, not to conjugate.
_IRREGULAR = {
    "wrote": "write", "written": "write", "writing": "write",
    "built": "build", "building": "build",
    "broke": "break", "broken": "break", "breaking": "break",
    "ran": "run", "running": "run",
    "caught": "catch", "catching": "catch",
    "sent": "send", "sending": "send",
    "held": "hold", "holding": "hold",
    "read": "read", "reading": "read",
    "left": "leave", "leaving": "leave",
    "made": "make", "making": "make",
}


def _stem(word: str) -> str:
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    for ending in _ENDINGS:
        if len(word) - len(ending) >= 4 and word.endswith(ending):
            word = word[: -len(ending)]
            break
    # A trailing e goes too, so parse, parser and parsing all land on pars.
    # Adding the e back instead was worse: it depended on which ending was
    # stripped, so parser and parsing disagreed.
    return word[:-1] if len(word) > 4 and word.endswith("e") else word


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


@server.tool()
def remember(
    fact: str, about: str, claiming: bool = False, ctx: Context | None = None
) -> str:
    """Write something back, so the next session in any agent knows it too.

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


@server.tool()
def sources(claim: str, ctx: Context | None = None) -> str:
    """Which file, session or commit a claim came from."""
    repo = _repo()
    if repo is None:
        return NOT_POINTED
    with Memory(repo) as mem:
        found = answer.ask(repo, mem, claim, identity=private.AGENT, limit=6)
        # Every tool an agent can call says when somebody else is mid-change,
        # so which one it happened to reach for does not decide whether it
        # finds out.
        busy = _being_worked_on(mem, claim, asker=_who(ctx))
    if not found:
        return f"{busy}\n\nNo source for that." if busy else "No source for that."
    seen, lines = set(), []
    if busy:
        lines.append(busy)
    for p in found:
        if p.where in seen:
            continue
        seen.add(p.where)
        lines.append(f"{p.source}: {p.where}")
    return "\n".join(lines)


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
