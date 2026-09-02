"""What a person sees when they do not know what to type.

One screen. Twenty-four lines or fewer, eighty columns or narrower, and no
word that a developer would have to look up. There is no mention of MCP,
tiers, indexes, graphs or servers, because none of that is something the
person asking for help needs to do.
"""

from __future__ import annotations

MAIN = """  knos — one local memory every coding agent on this machine shares,
         and it knows which of them is in your code right now

  Setup was one line:  pip install knos && knos connect
  Claude Code needs no restart; Claude Desktop and Cursor read their
  settings at startup, so restart those. Nothing leaves this machine.

  Four things you might type:

      knos ask "what are the rules here?"
      knos claim "the parser"    your agents are refused until: knos done
      knos status                what it read, and who is holding what

  More
      knos remember, notes, forget    things you tell your agents
      knos private                    keep a path from them
      knos point .                    re-read after a lot of changes
      knos help <cmd>                 more about one command

  While one agent is mid-change, the others are told, and knos holds
  back what it knows. A CLAUDE.md cannot do that: a file has no idea
  who is reading it, or when."""


PER_COMMAND = {
    "point": """\
  knos point .           re-read the repo, and read its code structure
  knos point ~/work/api  read another one

  It reads three things: what past agent sessions said, what your commits
  say, and how the code is put together. Secrets are left out.

  Run it again whenever you want it to catch up: it re-reads from scratch,
  so twice in a row is the same as once. It never runs on its own.""",
    "ask": """\
  knos ask "why did we drop redis?"

  Answers come back as what was actually said or written, and under each
  one, where it came from: a file and line, a session and a date, or a
  commit. knos does not write the answer itself, so there is nothing to
  double-check except the source.

  Ask about another repo:  knos ask "..." --in ~/work/api""",
    "status": """\
  knos status

  What knos has read, which agents it found history for, and how many
  kinds of secret it is keeping from them.""",
    "connect": """\
  knos connect           add knos to every agent you have, keeping a copy
                         of each settings file as it was
  knos connect --print   just show what to paste, and change nothing

  Your other agent then knows everything this one does. One store, not a
  CLAUDE.md and an AGENTS.md and a rules file drifting apart.

  Restart the agent afterwards. It gets four tools.""",
    "notes": """\
  knos notes             what your agents have written down
  knos forget <name>     drop one of them

  Your sessions, commits and code are read fresh every time you run
  knos point, so there is nothing to tidy there. These are the things an
  agent chose to write down, which is the part a CLAUDE.md used to hold.

  Forgetting one stops your agents repeating it.""",
    "claim": """\
  knos claim "the risk guard"

  Says you are working on something. Your agents are then withheld from
  it: they are told you hold it, not what knos knows about it.

  An agent can take it anyway, but only by giving a reason, and the
  reason goes in the journal under its name.

  It lapses after half an hour, or when you say:  knos done""",
    "done": """\
  knos done

  An agent starting a piece of work says so, and knos then withholds what
  it knows about it from your other agents. This says that is over.

  It says so by itself after half an hour anyway, because a warning that
  is always on is one nobody reads.""",
    "forget": """\
  knos forget "deploy window"

  Drops something your agents wrote down. They stop repeating it.

  See what there is first:  knos notes""",
    "private": """\
  knos private .env
  knos private notes/salary.md

  That path stops reaching your agents. Not blanked out, not counted:
  they are told nothing about it at all.

  You can still search it yourself.

  Already private without asking: .env, keys, certificates, .ssh, .aws.""",
}


def main() -> str:
    return MAIN


def for_command(name: str) -> str:
    known = PER_COMMAND.get(name)
    if known:
        return known
    return (
        f"  No command called {name}.\n\n"
        "  See what there is:  knos help"
    )
