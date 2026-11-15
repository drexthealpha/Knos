"""What a person sees when they do not know what to type. One screen, 80 columns."""

from __future__ import annotations

MAIN = """  knos - AI agent work gets paid only when GitHub's own signature, checked
         by Solana, proves it passed.

  One product, at drexthealpha.github.io/Knos (Solana devnet):
      1. paste an agent PR       see whether its "tests pass" is true
      2. protect a repo          two clicks: the proof workflow runs its checks
      3. fund an issue           your price waits in escrow on Solana
      4. paid on GitHub's proof  GitHub signs the run, the escrow checks it,
                                 the agent is paid; no proof, you get it back

  Free: the Stop hook. Your coding agent cannot say done until it is proved.
      knos init                  wire Claude Code, Codex, Cursor, OpenCode
      knos proof check "..."     run every check a claim needs, now
      knos proof learn / lint    past false "done"s become required checks
      knos prove --job ID --jwt-file token.txt   pay a job on its proof

  More
      knos ask, remember, notes, forget, private, point, compact, reset, memory
      knos status, doctor, bench, demo, learn, lint, export, restore
      knos labs                  claims, budgets, Pro, Tempo, text jobs, relay
      knos help <cmd>            more about one command"""


PER_COMMAND = {
    "proof": """\
  knos proof check "Done: tests pass, CI green"  run every check it needs
  knos proof observe SHA ci --failed            record what really happened
  knos proof lint                               claims the evidence contradicts
  knos proof learn                              make them required checks
  knos proof receipt "..." [--publish]          evidence root; devnet receipt
  knos proof run                                every [[check]], no claim (CI)

  The Stop hook from `knos init` runs these on the agent's last message: tests
  in a fresh venv, every CI job for HEAD, PyPI, URLs, deleted files, the commit
  author, and .knos/proof.toml. Each repo's proof history lives in Sibyl.""",
    "init": """\
  knos init                  add knos to every agent found on this machine
  knos init --hosts claude,cursor
  knos init --undo           take out everything it added
  knos init --print          show what it would write, change nothing

  Writes the memory server (MCP) into each agent's config, and for Claude
  Code, Codex, Cursor and OpenCode the edit guard and session notice. Every
  file is copied to ~/.knos/backups first. Then it starts the server once
  to prove it answers.""",
    "ask": """\
  knos ask "why did we drop redis?"
  knos ask "..." --in ~/work/api

  Answers are what was actually said or written - past agent sessions,
  commits, your instruction files, the code - each with its source. If a
  file in the answer is claimed by another agent, it says who has it.""",
    "claim": """\
  knos claim "the parser" -p src/parser/** -p tests/test_parser.py
  knos claim "fix handler_12" --for 60

  Other agents' edits to those files are refused by the edit guard until
  you run knos done or the claim lapses (30 minutes by default). Your own
  edits never are. Without -p, knos looks for exact file and symbol names
  in what you wrote; if none match, the claim is advisory: others are
  told, nothing is blocked.""",
    "done": """\
  knos done                  release all of your claims here
  knos done "the parser"     release one
  knos done --all            release every agent's (asks first)

  Only ever your own, unless you say --all.""",
    "point": """\
  knos point                 read what is new since last time, now

  knos reads a repo by itself the first time you ask, and catches up when
  something changed. This is the same thing on demand. It never deletes;
  to start over, knos reset --yes (which keeps a backup).""",
    "reset": """\
  knos reset --yes

  Starts this repo's memory over. The store is copied to ~/.knos/backups
  first, notes included.""",
    "status": """\
  knos status

  What knos has read, what is claimed and by whom, whether the edit guard
  is wired, and which store it uses.""",
    "remember": """\
  knos remember "we dropped redis because the cache was never the problem"

  Every agent you connect will know it, as your words. If the store has no
  room, it says so and writes nothing.""",
    "notes": "  knos notes\n\n  What has been written down.  Drop one:  knos forget <name>",
    "forget": "  knos forget \"deploy window\"\n\n  Archives a note so agents stop repeating it.",
    "private": """\
  knos private notes/salary.md

  That path stops reaching your agents: not blanked, not counted. You can
  still search it yourself. Already private: .env, keys, certificates,
  .ssh, .aws.""",
    "board": """\
  knos board

  A live page of this repo on 127.0.0.1 with a one-off token: claims,
  agents seen today, recent refusals, and spend when Pro is on.""",
    "bench": """\
  knos bench --out bench.md

  Collisions, wrong refusals, recall and speed, against the simplest way
  of doing without knos. Runs in a temporary folder.""",
    "jobs": """\
  knos jobs post "TITLE" --task "..." --price 2   the price waits in escrow
  knos jobs get ID / accept ID / reject ID        pay only for accepted work
  knos jobs list [--mine]   stats [--agents]   serve (Blinks + web app)
  knos jobs release ID / refund ID / prefs / sibyl / relay

  Hire any AI agent. 2.5% fee, paid on proof. Devnet by default.""",
    "work": """\
  KNOS_WORKER_MODEL=groq:llama-3.3-70b-versatile knos work

  Take open jobs with your own model key, run each brief's checks, deliver
  sealed to the buyer. Paid when the buyer accepts.""",
    "verify": """\
  knos jobs post "TITLE" --price 2 --verify knos   name a verifier
  knos verify ID --key PATH        check one delivered job, then settle it
  knos verify --all --once         every delivered job naming your key

  Re-runs the brief's checks and the buyer's saved preferences: pays the
  worker on pass, refunds the buyer on fail. Prints a signed verdict.""",
    "demo": "  knos demo\n\n  The whole product on a throwaway repo. Every line is a real call.",
    "worth": "  knos worth\n\n  Claims taken and released, and edits refused, counted from the record.",
    "spend": """\
  knos spend                 today, per agent and model
  knos spend --days 7

  Knos Pro. Read from Claude Code's and Codex's own logs, priced at API
  list prices. Nothing leaves the machine.""",
    "budget": """\
  knos budget set 20 --per day      one cap: model tokens + API payments
  knos budget set 5 --repo .        count and cap only this repo
  knos budget raise 10
  knos budget clear
  knos budget set claude 5/day --chain tempo    Tempo enforces it per day
  knos budget set claude 20 --chain solana      a Solana delegate of 20
  knos budget show                  every chain limit, read live
  knos budget revoke claude --chain tempo
  knos budget fund --agent claude 5 --chain tempo    an agent's own wallet
  knos budget agents                each wallet: cap, spent, balance
  knos budget sweep --agent claude --to <your address>

  Knos Pro. Past the cap, the edit guard refuses your agents' edits and
  says why, until a person raises it. An agent wallet holds only what you
  fund it with, so the chain itself stops it at that amount.""",
    "report": """\
  knos report                last 7 days
  knos report --days 30 --out report.md

  Knos Pro. Spend by agent and model, agents' API payments against their
  caps, and in this repo: claims taken and edits refused.""",
    "pay": """\
  knos pay https://api.example.com/paid --agent claude

  Knos Pro. Fetches an API; if it answers 402 Payment Required (MPP on
  Tempo, or x402 on Solana), pays it from that agent's own wallet, inside
  its cap. Agents get the same thing as the `pay` tool.""",
    "pro": """\
  knos pro                   status and plans
  knos pro buy               22 USDC / 30 days, Sibyl Pro included
  knos pro buy --year        208 USDC / year
  knos pro buy --chain tempo pay with USDC.e or pathUSD on Tempo
  knos pro buy --network devnet     try it with devnet USDC (testnet: Tempo)
  knos pro activate <code>   or:  knos pro activate --tempo <tx>

  14 days free. Memory, claims and the guard are free forever (MIT).""",
    "team": """\
  knos team create --cluster devnet   a registry on Solana; commit its file
  knos team add <join code>           a teammate (their knos init prints it)
  knos team add x --cloud ci          a revocable key for a cloud sandbox
  knos team status | remove <who> | leave
  knos team key export | import       your key on your other machines

  A claim on one machine refuses a conflicting edit on every other machine
  in the team, from any agent, with no server. The chain holds only salted
  hashes. If the chain is unreachable, edits go ahead locally (warned).""",
    "doctor": """\
  knos doctor                        which agents and machines are guarded

  Each agent host's edit guard, this repo's commit guard and committed repo
  hooks; in a team, this key's float and members quiet on chain.""",
    "stats": """\
  knos stats                         claims and refused conflicts, in counts
  knos stats --share                 the same as one line to paste anywhere

  Counts only: no path, repo detail or name leaves in the shared line.""",
    "prove": """\
  knos prove "decided to shard by tenant"   an inclusion proof: that fact was
                                            in an agent's record on chain
  knos prove --job ID --jwt-file token.txt  pay a GitHub-posted job on its
                                            Actions proof (prove.yml)

  The leaf, its Merkle path and the record's root, all checkable by anyone
  holding the salted log.""",
    "learn": """\
  knos learn                         one pass of Sibyl's self-learning here
  knos learn --show                  pending proposals
  knos learn --accept <id>           it becomes .knos/playbooks/<slug>.md

  Sibyl Pro, included in knos pro buy. Commit accepted
  playbooks: every machine imports them into Sibyl at session start.""",
    "lint": """\
  knos lint                          Sibyl's memory linter, plus agents that
                                     recorded opposite things

  Sibyl Pro, included in knos pro buy.""",
    "agent": """\
  knos agent record codex             claims taken, finished, abandoned, and
                                      collisions, checked against the chain

  In a team, each agent's day is written to Solana as a record: counters and
  a Merkle root over its salted log, signed by its member key. Anyone can read
  it; this machine's log proves each line of it.""",
    "compact": """\
  knos compact
  knos compact --older-than 7

  Makes room in Sibyl memory: drops notes forgotten long ago and gives the
  freed space back. Nothing an answer uses is lost. Past Sibyl's free 5 MB:
  knos pro buy, which includes Sibyl Pro (no cap)""",
    "export": "  knos export\n\n  Writes .knos/decisions.md: decisions and current claims, to commit.",
    "restore": "  knos restore\n\n  Reads .knos/decisions.md back. Claims are not restored.",
    "who": "  knos who\n\n  Which agents close what they claim, and the hold that has earned them.",
    "mainnet-check": """\
  knos mainnet-check   every gate before mainnet: a Squads vault holds the
                       upgrade authority, the admin and the fees; a verified
                       build; security.txt; IDL on chain; cargo-audit clean.
                       Mainnet stays locked.""",
    "memory": """\
  knos memory export [--out FILE]   every Sibyl record here: JSON + sha256
  knos memory import FILE           merge one back; safe to run twice
  knos memory note "..."            what the next session here starts with""",
    "labs": """\
  knos labs claim "the parser" -p src/parser/**   claims between agents
  knos labs team create / budget / spend / report / pay / pro
  knos labs jobs post "TITLE"     text jobs: the price waits in escrow
  knos labs work / verify / jobs relay            be hired; Tempo, ERC-8183

  Experiments outside the one product. The old names (knos claim, knos
  budget, knos jobs, ...) still work.""",
}
PER_COMMAND["connect"] = PER_COMMAND["init"]
PER_COMMAND["guard"] = PER_COMMAND["init"]


def main() -> str:
    return MAIN


def for_command(name: str) -> str:
    return PER_COMMAND.get(name) or f"  No command called {name}.\n\n  See what there is:  knos help"
