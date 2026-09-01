"""What a person sees when they do not know what to type.

One screen. Twenty-four lines or fewer, eighty columns or narrower, and no
word that a developer would have to look up. There is no mention of MCP,
tiers, indexes, graphs or servers, because none of that is something the
person asking for help needs to do.
"""

from __future__ import annotations

MAIN = """\
  knos — one memory for every coding agent here, and it knows
         which of them is in your code right now

  knos point .                 read this repo
  knos ask "your question"     ask about it
  knos connect                 let your agents use it

  Examples
      knos ask "why did we drop redis?"
      knos ask "who touched auth last?"

  More
      knos remember    tell your agents something
      knos notes       what they have been told
      knos forget      drop one of them
      knos done        say you have finished
      knos status      what it has read
      knos private     keep a path from your agents
      knos help <cmd>  more about one command

  While one agent is mid-change, the others are told, and knos holds
  back what it knows until you sort it out. A CLAUDE.md cannot do that.

  Nothing leaves this machine."""


PER_COMMAND = {
    "point": """\
  knos point .           read the repo you are standing in
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
  knos connect           print what to paste, for every agent you have
  knos connect --write   add it for them, keeping a copy of what was there

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
