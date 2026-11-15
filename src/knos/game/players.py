"""Who plays. Every player goes through the game's one door (Game.submit); none of them decides (the referee does).

    nemotron(...)        an AI scientist on Nemotron 3 Super through Nebius Token Factory (knos.nebius). Live when
                         NEBIUS_API_KEY is set; otherwise every reply is MOCK (synthetic, not a real API response),
                         made locally and labelled on the player and in the record.
    claude_agent(...)    an AI scientist on the Claude Agent SDK (claude-agent-sdk, Claude Code as a library), model
                         claude-opus-5-5, no tools at all (it reads the prompt and writes the file; the referee runs
                         it). Needs ANTHROPIC_API_KEY (and the package); without them it does not play and says why.
    command(...)         any other agent behind a command line (prompt on stdin, the new file on stdout), the same
                         protocol as knos.autoresearch's CommandProposer: `claude -p`, `codex exec -`, `hermes ...`,
                         or `python -m knos.game.local_agent` (no model: deterministic hill-climbing, labelled).
    agents over MCP      any MCP host plays with the tools knos_game_state / _data / _join / _submit / _board / _mine.
    SyntheticHuman       a scripted stand-in for a person, labelled "synthetic scripted human" everywhere: it edits
                         the CONFIG block the way a person tuning by hand might. Real people play on the web page.

`play(game, pid, proposer)` builds the proposer's prompt from what the player may see (the goal, its own best file,
its own history: decisions, rule names, shown scores, its own validation score; never a hidden score) and submits.
"""
from __future__ import annotations

import asyncio
import os

from ..autoresearch import proposers
from .engine import Game, GameError

CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_SYSTEM = ("You are an AI scientist playing a Knos game. You improve ONE Python file for a sealed research goal. The Knos "
                 "referee judges every attempt on data you never see and refuses cheats (other files, new imports, reading sealed "
                 "data). Reply with the whole file only.")


class PlayerUnavailable(RuntimeError):
    """This player cannot play here (no key, no package): the sentence says which."""


def context(game: Game, pid: str) -> proposers.Context:
    hist = []
    for h in game.history(pid):
        hist.append({"iteration": h["n"], "change": f"attempt {h['n']}", "agent": pid, "decision": h["decision"],
                     "reasons": (h["rules"] or h["reasons"])[:3] + ([f"shown score {h['shown']}"] if h["shown"] is not None else []),
                     "reported": {"val_accuracy": h["reported_val"]} if h["reported_val"] is not None else {}})
    t = game.task
    return proposers.Context(t.program, t.idea, t.editable, game.best_source(pid), hist)


def play(game: Game, pid: str, proposer) -> dict:
    """One attempt by an agent player. Returns the referee's answer, or {"skipped": why} when the agent proposed nothing."""
    cand = proposer.propose(context(game, pid))
    if cand is None:
        return {"skipped": f"{getattr(proposer, 'name', 'the agent')} proposed nothing"}
    got = game.submit(pid, cand.files)
    got["change"] = cand.change
    return got


# -- Nemotron (Nebius Token Factory) ------------------------------------------------------------------------------------
def nemotron(cheat_at: tuple = (2,)):
    """(proposer, label). MOCK unless NEBIUS_API_KEY is set; the mock coder proposes once (at `cheat_at`) a file that
    reads the referee's sealed file, so a game shows the referee refusing an AI scientist's cheat."""
    from ..nebius import coder, mock, sources
    from ..nebius.tokenfactory import TokenFactory
    ar = mock.autoresearch_responder(cheat_at=cheat_at)

    def respond(model, messages):
        user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return ar(user)
    client = TokenFactory(responder=respond)
    label = f"Nemotron 3 Super on Nebius Token Factory ({sources.SUPER})" if client.live else f"{sources.MOCK}: Nemotron replies made locally (NEBIUS_API_KEY not set)"
    return coder.NemotronProposer(client), label


# -- Claude Agent SDK -----------------------------------------------------------------------------------------------------
class ClaudeAgentProposer:
    """A knos.autoresearch proposer on the Claude Agent SDK: one `query` with no tools, max one turn; the reply's last
    ```python block is the file. `query_fn` replaces claude_agent_sdk.query (tests)."""

    name = "claude-agent-sdk:" + CLAUDE_MODEL

    def __init__(self, query_fn=None, options=None, model: str = CLAUDE_MODEL):
        self.model = model
        if query_fn is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise PlayerUnavailable("the Claude Agent SDK player needs ANTHROPIC_API_KEY (not set): it does not play")
            try:
                from claude_agent_sdk import ClaudeAgentOptions, query  # type: ignore[import-not-found]
            except ImportError:
                raise PlayerUnavailable("the Claude Agent SDK player needs the claude-agent-sdk package (pip install claude-agent-sdk)") from None
            query_fn = query
            options = options or ClaudeAgentOptions(system_prompt=CLAUDE_SYSTEM, model=model, allowed_tools=[], max_turns=1,
                                                    permission_mode="dontAsk")
        self.query_fn, self.options = query_fn, options
        self.cost_usd: float | None = None

    async def _ask(self, text: str) -> str:
        parts: list[str] = []
        async for m in self.query_fn(prompt=text, options=self.options):
            for block in getattr(m, "content", None) or []:
                if hasattr(block, "text") and isinstance(block.text, str):
                    parts.append(block.text)
            if getattr(m, "total_cost_usd", None) is not None:
                self.cost_usd = m.total_cost_usd
            if getattr(m, "result", None) and not parts:
                parts.append(m.result)
        return "\n".join(parts)

    def propose(self, ctx: proposers.Context) -> proposers.Candidate | None:
        text = asyncio.run(self._ask(proposers.prompt(ctx)))
        if "```" not in text:
            return None
        src, change = proposers.parse_reply(text)
        return proposers.Candidate({ctx.editable: src}, self.name, change)


def claude_agent(query_fn=None):
    """(proposer, label). Raises PlayerUnavailable without ANTHROPIC_API_KEY or the package."""
    p = ClaudeAgentProposer(query_fn=query_fn)
    return p, ("Claude Agent SDK, " + CLAUDE_MODEL) if query_fn is None else "Claude Agent SDK adapter with a scripted query (test, not a model)"


# -- any agent behind a command line ----------------------------------------------------------------------------------------
def command(cmdline: str, timeout_s: float = 600.0):
    p = proposers.CommandProposer(cmdline, timeout_s=timeout_s)
    return p, f"agent behind a command: {cmdline.split()[0]}"


# -- a scripted stand-in for a person ---------------------------------------------------------------------------------------
class SyntheticHuman:
    """SYNTHETIC: a scripted player standing in for a person. It changes the CONFIG block one guess at a time, the way a
    person tuning by hand might (standardize the inputs, then add squared features, then more epochs)."""

    name = "synthetic-scripted-human"
    LABEL = "synthetic scripted human (not a person)"
    GUESSES = ({"standardize": True}, {"features": "square"}, {"epochs": 40}, {"lr": 0.1})

    def __init__(self):
        self.k = 0

    def propose(self, ctx: proposers.Context) -> proposers.Candidate | None:
        cfg = proposers.read_config(ctx.best)
        while self.k < len(self.GUESSES):
            g = self.GUESSES[self.k]
            self.k += 1
            new = {**cfg, **{k: v for k, v in g.items() if k in cfg}}
            if new != cfg:
                return proposers.Candidate({ctx.editable: proposers.write_config(ctx.best, new)}, self.name,
                                           ", ".join(f"{k} -> {v!r}" for k, v in g.items()))
        return None


__all__ = ["ClaudeAgentProposer", "GameError", "PlayerUnavailable", "SyntheticHuman", "claude_agent", "command", "context", "nemotron", "play"]
