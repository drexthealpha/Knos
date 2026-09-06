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
    "changed": """\
  knos changed "the risk guard" "unknown assets pass with a warning"

  Says a decision has been reversed. The old wording is archived rather
  than dropped, so "why did we do it that way" still has an answer.

  Everything on the same subject is then held: an agent editing it is
  refused, and a paid answer about it is refused, until somebody says
  they have looked.

  See what is held:  knos held
  Clear one:         knos reconsider, naming the thing.""",
    "reconsider": """\
  knos reconsider "the risk guard tests"

  Says you have looked at something again after the decision under it
  changed. Work on it stops being held.

  It costs one line, on purpose. Carrying on without looking is the only
  expensive path here.""",
    "held": """\
  knos held

  What knos is holding, and why. Each one names the decision that
  changed, what it used to say, and what it says now.

  Nothing is held forever: reconsider it, naming the thing.""",
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
    "remember": """  knos remember "we dropped redis because the cache was never the problem"

  Tells your agents something they would otherwise have to be told again
  in every session. It comes back as your own words, under your name.

  See what there is:  knos notes      Drop one:  knos forget""",
    "export": """  knos export

  Writes .knos/decisions.md: what you have told your agents, and what is
  claimed right now. Commit it. A fresh clone reads it on its first
  question, so the decisions outlive this machine.

  Claims in it are a snapshot. They lapse after half an hour, so a claim
  written into the file is not one that is still held when it is read.

  --to writes somewhere else, if your repo already keeps decisions
  somewhere: knos export --to docs/decisions/0001-knos.md

  Knos reads .knos/decisions.md, DECISIONS.md, WORKLOG.md and docs/adr/*.md
  back on the next question. Write anywhere else and the file is still
  written and still worth committing, but the next agent will not find it,
  and knos export says so rather than letting you assume otherwise.""",
    "guard": """  knos guard --install

  Everything else knos does is decline to answer. This refuses the edit.

  Claude Code, Cursor and OpenCode each run a hook before a tool call, and
  a hook can say no. With the guard installed, an agent about to edit a file
  that belongs to work another agent has claimed is stopped and told who has
  it, and so is an agent about to edit a path this repo's own CLAUDE.md or
  AGENTS.md forbids in words a machine can check - "never edit `src/gen/`"
  is a pattern, "write idiomatic code" is not, and only the first kind is
  ever read.

  Off unless you run it, because a hook that refuses wrongly is worse than
  no hook. Every file it edits is copied to <name>.before-knos first, and
  `knos guard --uninstall` takes all of it back out. If the store cannot be
  read, the guard allows the edit: it is a refinement on the claim, never a
  gate in front of your own disk.

  Claude Desktop is not in the list. It has no hooks.""",
    "share": """  knos share ~/work/api/docs alice

  Lets a teammate's agent read one folder of this repo, and nothing else.
  Everything not shared stays invisible to them, not redacted.

  Stop it again:  knos unshare ~/work/api/docs alice""",
    "unshare": """  knos unshare ~/work/api/docs alice

  Stops a teammate's agent reading a folder you shared. From the next
  question on, they are told nothing about it.""",
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
