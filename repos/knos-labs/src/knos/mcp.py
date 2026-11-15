"""The MCP server. Local stdio, launched by the client. Nothing hosted.

Tools: search, about, remember (optionally claiming files), done; pay; and the jobs tools post_job, find_jobs,
claim_job, deliver_job. Every answer that touches claimed files says who holds them; nothing an agent asks is ever
hidden. Claims are enforced where edits happen, by the edit guard
(`guard.py`), not by withholding memory.

The server answers only for the repo it was started in. It never falls back to another repo.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from . import version
from . import answer, code, private
from . import paths as knos_paths
from .memory import TOPIC, Fact, Memory

server = MCPServer("knos", version=version(), instructions=(
    "One local memory every coding agent on this machine shares, and the list of which files each of them is "
    "working on right now.\n\n"
    "Search it before asking the person to repeat themselves: what past sessions decided (in any agent), what "
    "commits changed and why, what this repo's CLAUDE.md and AGENTS.md say, and how the code is structured. Every "
    "result names its source.\n\n"
    "Before you change files, claim them: remember(fact, about, claiming=true, paths=[...]). Another agent's edit "
    "to a claimed file is refused by the knos edit guard; yours never is. Call done() when you finish, so others "
    "stop waiting. If a file you need is claimed, you are told who holds it and since when.\n\n"
    "Jobs: post_job hires any AI agent (the price waits in escrow, paid only on acceptance); find_jobs, claim_job and "
    "deliver_job let you be hired and paid for work a buyer accepts."
))

NOT_A_REPO = (
    "knos: this session is not inside a git repository, so there is no repo memory here. "
    "Start the agent inside your project folder."
)
FULL = (
    "knos: the memory store is full (Sibyl's free 5 MB), and nothing was written. "
    "Fix: knos compact, or knos pro buy (Sibyl Pro, uncapped, is included)."
)

FIRST_READ_BUDGET = 12.0
from .refresh import PARTIAL  # noqa: E402  (the marker refresh.ensure writes after a cut-off read)


def _unfinished(mem) -> str:
    try:
        got = mem.reference(PARTIAL)
    except Exception:
        return ""
    if not got:
        return ""
    body = got.get("body") if isinstance(got, dict) else None
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            body = {}
    if not isinstance(body, dict) or not body.get("partial"):
        return ""
    read = int(body.get("sessions", 0)) + int(body.get("commits", 0))
    return (f"\n\n[knos has not finished reading this repo: the first question has to answer quickly, so it read "
            f"{read} things and stopped. The next question, or `knos point`, reads the rest.]")


def _repo() -> Path | None:
    """The repo this session is in, read on the spot the first time and refreshed when it changed. None when the
    session is not in a git repo: never another repo, never the last one somebody pointed at."""
    here = knos_paths.repo_here()
    if here is None:
        return None
    from . import refresh
    try:
        refresh.ensure(here, budget=FIRST_READ_BUDGET)
    except Exception:
        # an unreadable repo is still this repo: answer from what is stored
        pass
    return here


def _agent(repo: Path, ctx: Context | None):
    from . import identity
    from .claims import lookup_session

    name = ""
    if ctx is not None:
        try:
            name = (ctx.request_context.session.client_params.client_info.name or "").strip()
        except Exception:
            name = ""
    return identity.for_mcp(name or "agent", lookup_session(repo))


def _recalled(mem, query: str, shown: set[str], limit: int) -> list[str]:
    """knos.recall over the past conversations this repo's sessions hold: what answer.ask did not already return."""
    from . import recall
    try:
        rows = recall.retrieve(mem.client, query, k=limit)
    except Exception:
        return []
    out = []
    for r in rows:
        text = r["text"].split(": ", 1)[-1].strip()
        if text and text not in shown and not private._quotes_a_secret({"text": text}):
            shown.add(text)
            out.append(f"{text}\n    source: {r.get('where') or 'past session ' + str(r.get('date') or '')}")
    return out


def _team_claim(repo: Path, globs: list[str], agent) -> str | None:
    """In a team, the same claim on Solana (knos.team.live.explicit): who holds it when another machine won."""
    try:
        from .team import live
    except ImportError:
        return None
    return live.explicit(repo, globs, agent.host, agent.session or (f"pid{agent.anchor}" if agent.anchor else ""))


def _team_release(repo: Path, agent) -> None:
    try:
        from .team import live
    except ImportError:
        return
    live.explicit_release(repo, agent.host, agent.session or (f"pid{agent.anchor}" if agent.anchor else ""))


def _claim_notes(repo: Path, text: str, agent) -> str:
    """Who holds files this question or answer mentions. Annotation only."""
    from .claims import Claims, claims_db

    if not claims_db(repo).exists():
        return ""
    try:
        with Claims(repo) as c:
            held = [x for x in c.about(text) if not x.held_by(agent)]
    except Exception:
        return ""
    lines = []
    for x in held:
        from .guard import _since
        where = ", ".join(x.globs[:3]) if x.globs else "(no files)"
        lines.append(f"[claimed] {where} is claimed by {x.label} since {_since(x.taken_at)} ({x.description}).")
    return "\n".join(lines)


@server.tool(annotations=ToolAnnotations(title="Search memory", read_only_hint=True, destructive_hint=False,
                                         idempotent_hint=True, open_world_hint=False))
def search(query: str, limit: int = 8, ctx: Context | None = None) -> str:
    """Search this repo's shared memory: past agent sessions from every host, commits, instruction files and code
    structure. Reads only. Every result names where it came from. Results that touch files another agent has
    claimed say who holds them."""
    repo = _repo()
    if repo is None:
        return NOT_A_REPO
    with Memory(repo) as mem:
        found = answer.ask(repo, mem, query, identity=private.AGENT, limit=limit)
        recalled = _recalled(mem, query, {p.text.strip() for p in found}, limit)
        tail = _unfinished(mem)
    if found or recalled:
        answered = "\n\n".join([f"{p.text.strip()}\n    source: {p.where}" for p in found] + recalled)
    else:
        answered = "Nothing known about that."
    if answer.looks_structural(query) and not code.indexed(repo):
        answered += ("\n\n(knos has not read this repo's code structure yet: `knos point` reads it. Sessions, commits "
                     "and instruction files answered this.)")
    notes = _claim_notes(repo, query + "\n" + "\n".join(p.text + " " + p.where for p in found), _agent(repo, ctx))
    return (notes + "\n\n" if notes else "") + answered + tail


@server.tool(annotations=ToolAnnotations(title="Look up one thing", read_only_hint=True, destructive_hint=False,
                                         idempotent_hint=True, open_world_hint=False))
def about(thing: str, ctx: Context | None = None) -> str:
    """Everything known about one named thing: a file, a person, a topic. Reads only."""
    repo = _repo()
    if repo is None:
        return NOT_A_REPO
    with Memory(repo) as mem:
        known = []
        for category in ("file", "person", "topic", "symbol"):
            record = mem.thing(category, thing)
            if not record:
                continue
            body = record.get("body") or {}
            said = body.get("note") or body.get("last_commit") or ""
            if said and private._quotes_a_secret({"text": said}):
                continue
            when = body.get("when") or body.get("last_seen") or ""
            known.append(f"{said}\n    source: written down, {when}" if said else f"{category}: {thing}")
        found = answer.ask(repo, mem, thing, identity=private.AGENT, limit=5)
        tail = _unfinished(mem)
    said = {p.text.strip() for p in found}
    lines = [k for k in known if k.split("\n")[0] not in said]
    lines += [f"{p.text.strip()}\n    source: {p.where}" for p in found]
    notes = _claim_notes(repo, thing, _agent(repo, ctx))
    if notes:
        lines.insert(0, notes)
    return ("\n\n".join(lines) if lines else f"Nothing known about {thing}.") + tail


@server.tool(annotations=ToolAnnotations(title="Say you have finished", read_only_hint=False, destructive_hint=False,
                                         idempotent_hint=True, open_world_hint=False))
def done(about: str = "", ctx: Context | None = None) -> str:
    """Release the files you claimed, so other agents can edit them. Only ever your own claims: give `about` (the
    claim's description or id) to release one, or leave it empty to release all of yours."""
    from . import record
    from .claims import Claims

    repo = _repo()
    if repo is None:
        return NOT_A_REPO
    agent = _agent(repo, ctx)
    with Claims(repo) as c:
        gone = c.release(agent, about.strip())
    if gone:
        _team_release(repo, agent)
        try:
            with Memory(repo) as mem:
                for x in gone:
                    record.note_finished(mem, x.description, agent.host)
        except Exception:
            pass
    if not gone:
        return (f"You hold no claim on {about} here." if about else "You hold no claims here.") + \
            " Claims are per agent: this only ever releases your own."
    return "Released: " + "; ".join(f"{x.description} ({', '.join(x.globs) or 'advisory'})" for x in gone) + "."


@server.tool(annotations=ToolAnnotations(title="Write to memory", read_only_hint=False, destructive_hint=False,
                                         idempotent_hint=False, open_world_hint=False))
def remember(fact: str, about: str, claiming: bool = False, paths: list[str] | None = None,
             ctx: Context | None = None) -> str:
    """Write something down so the next session in any agent knows it too. Appends; never edits or deletes.

    Set `claiming` when you are about to change files, and list them in `paths` (files, folders or globs like
    `src/parser/**`). Another agent's edit to them is then refused until you call done() or the claim lapses
    (30 min, refreshed by claiming again). Without `paths`, knos resolves exact file and symbol names in `about`;
    if none resolve, the claim is advisory (shown to others, never blocking)."""
    from datetime import datetime, timezone

    from . import record
    from .claims import Claims

    repo = _repo()
    if repo is None:
        return NOT_A_REPO
    now = datetime.now(timezone.utc).isoformat()
    agent = _agent(repo, ctx)
    with Memory(repo) as mem:
        written = mem.record(Fact(text=fact, source="note", where=f"{agent.label} said so, {now[:10]}", when=now, about=about))
        if written is None:
            return FULL
        mem.note_thing(TOPIC, about, {"note": fact, "when": now[:10], "who": agent.label})
    with Memory(repo) as mem:
        holds = 30
        if claiming:
            try:
                holds = record.holds_for(mem, agent.host)
            except Exception:
                holds = 30
    if not claiming:
        return f"Remembered, about {about}."
    wanted = list(paths or [])
    try:
        with Claims(repo) as c:
            took, conflict, mine = c.take(agent, about, wanted or None, holds_min=holds)
    except Exception as why:  # say so, never crash the tool call
        return f"Remembered, about {about}. Not claimed: {why}. Nothing is blocked for anyone until it is."
    if not took and conflict is not None:
        from .guard import _since
        return (f"Remembered, about {about}. Not claimed: {', '.join(conflict.globs)} is held by {conflict.label} "
                f"since {_since(conflict.taken_at)} ({conflict.description}). Ask them, or take other work.")
    if mine is not None and not mine.advisory:
        held = _team_claim(repo, mine.globs, agent)
        if held:
            with Claims(repo) as c:
                c.release(agent, mine.id)
            return (f"Remembered, about {about}. Not claimed: {', '.join(mine.globs)} is held on another machine by "
                    f"{held}. Ask them, or take other work.")
    try:
        with Memory(repo) as mem:
            record.note_taken(mem, about, agent.host, now)
    except Exception:
        pass
    if mine is not None and mine.advisory:
        return (f"Remembered, about {about}. Claimed as advisory: no file or symbol named in it resolved, so other "
                "agents are told but nothing is blocked. Pass paths=[...] to guard files.")
    return f"Remembered, about {about}. Claimed {', '.join(mine.globs) if mine else ''} for {holds} min."


@server.tool(annotations=ToolAnnotations(title="Pay for an API", read_only_hint=False, destructive_hint=False,
                                         idempotent_hint=False, open_world_hint=True))
def pay(url: str, method: str = "GET", body: str = "", agent: str = "", ctx: Context | None = None) -> str:
    """Fetch an API that may answer HTTP 402 Payment Required, paying it (MPP on Tempo, or x402 on Solana) from this
    agent's own Knos budget wallet, inside the cap a person set with `knos budget fund`. Refused, with the reason,
    when there is no wallet or the payment would pass the cap. `agent` defaults to this host's name."""
    try:
        from .pro import agentpay
    except ImportError:
        return "knos: agent payments are part of Knos Pro, which is not installed here."
    who = agent.strip()
    if not who:
        repo = knos_paths.repo_here()
        who = _agent(repo, ctx).host if repo else "agent"
    try:
        got = agentpay.pay(who, url, method.upper() or "GET", body.encode() if body else None)
    except agentpay.Refused as why:
        return str(why)
    except Exception as why:  # a tool call never crashes the server
        return f"knos: the request failed ({type(why).__name__}: {why})"
    head = f"[paid {got.paid:g} on {got.chain} from {who}'s wallet]\n" if got.paid else ""
    return f"{head}HTTP {got.status}\n{got.body}"


_JOB = dict(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)


@server.tool(annotations=ToolAnnotations(title="Hire an agent", **_JOB))
def post_job(title: str, task: str, price_usdc: float, kind: str = "text", checks_json: str = "",
             work_minutes: int = 60, review_hours: int = 24) -> str:
    """Hire any AI agent for a job: the price goes into escrow on Solana and is paid only when the work is accepted
    (or refunded if nothing is delivered in time). kind: python, csv, json, copy or text. checks_json makes acceptance
    checkable, e.g. {"tests": "from solution import f
assert f(1) == 2"} or {"must_include": ["Ada"]}."""
    from .jobs import api
    return api.post_job(title, task, price_usdc, kind, checks_json, work_minutes, review_hours)


@server.tool(annotations=ToolAnnotations(title="Find paid jobs", read_only_hint=True, destructive_hint=False,
                                         idempotent_hint=True, open_world_hint=True))
def find_jobs(kind: str = "") -> str:
    """Open jobs on the Knos network you could take and be paid for: id, price, kind, title."""
    from .jobs import api
    return api.find_jobs(kind)


@server.tool(annotations=ToolAnnotations(title="Take a job", **_JOB))
def claim_job(job_id: str) -> str:
    """Claim an open job (exactly one agent can) and get its brief, checks and the buyer's preferences."""
    from .jobs import api
    return api.claim_job(job_id)


@server.tool(annotations=ToolAnnotations(title="Deliver a job", **_JOB))
def deliver_job(job_id: str, content: str) -> str:
    """Deliver a job you claimed. Its checks run first; then it is sealed to the buyer and its hash goes on chain."""
    from .jobs import api
    return api.deliver_job(job_id, content)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
