"""A Knos game: many attempts at once on one sealed goal, by people and AI scientists, judged by one referee.

Wall 3 of the valley of death is that single attempts fail. Foldit and EteRNA showed that people playing a scientific
game through one interface can solve real research problems; Knos puts AI scientists (Nemotron on Nebius Token
Factory, the Claude Agent SDK, any agent behind a command or over MCP) and people in the SAME game, through the SAME
calls, judged by the SAME referee, with funders pooling one pot across every attempt.

    knos.game.attempt(goal, player, kind, artifact)   one attempt, the same call for a person and an agent
    knos.game.split_pool(pool_units, attempts)        a pool divided by the referee's verdicts (proportional)
    knos.game.swhid(content)                          the Software Heritage id of a file's bytes
    knos.game.graduation_record(result, amount=...)   a graduated result's record: Zenodo deposit, fees.yaml fees

    knos.game.engine    Game: create (seal), join, submit (judged now on sealed data), board (Ladder scores), rounds,
                        finish (verdicts on a second sealed set, used once)
    knos.game.ladder    the public score (Blum and Hardt's Ladder: no leaderboard probing of the sealed set)
    knos.game.players   Nemotron, Claude Agent SDK, any command, a synthetic scripted human (labelled)
    knos.game.pot       the pooled pot as knos_pay orders (config/fees.yaml game_pot: at most 4 payees an order)
    knos.game.graduate  step 6: works + wanted + makeable, graduation vault and pre-orders, the contributor split,
                        Knos Record + Zenodo DOI + SWHIDs + devnet anchor
    knos.game.tools     MCP tools; knos.game.server the web page + JSON API; knos.game.cli `knos game`

docs/reference/AGENTS.md says what each part does and what it does not. This module imports nothing heavy.
"""
from __future__ import annotations

import hashlib

KINDS = ("human", "agent")


def _kind(kind) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind: one of {', '.join(KINDS)}, not {kind!r}")
    return kind


def attempt(goal, player, kind: str, artifact: bytes) -> dict:
    """One attempt at a goal, the same call for a person and an AI agent: {goal, player, kind, artifact_hash (sha256
    hex), size}. `goal` is a game id, or a knos.game.engine.Game: then the attempt is also submitted to it (the artifact
    is the game's one editable file, `player` the player id) and the referee's answer is under "referee"."""
    _kind(kind)
    if not isinstance(artifact, (bytes, bytearray)):
        raise TypeError("artifact: bytes")
    data = bytes(artifact)
    is_game = hasattr(goal, "submit") and hasattr(goal, "task")
    out = {"goal": goal.s["id"] if is_game else goal, "player": player, "kind": kind,
           "artifact_hash": hashlib.sha256(data).hexdigest(), "normalized_hash": _normalized(data), "size": len(data)}
    if is_game:
        p = goal.player(player)
        if p["kind"] != kind:
            raise ValueError(f"player {player} joined as {p['kind']}, not {kind}")
        out["referee"] = goal.submit(player, {goal.task.editable: data.decode("utf-8")})
    return out


def _normalized(data: bytes) -> str:
    from .norm import normalized_sha256
    return normalized_sha256(data.decode("utf-8", errors="replace"))


def split_pool(pool_units: int, attempts) -> dict:
    """A pool divided by the referee's verdicts: {player: units}. Only verified attempts with a score above 0 count; each
    player is paid in proportion to their best verified score, people and agents by the same rule. Integers that sum
    exactly to the pool (each share rounded down, the units left over one each to the largest remainders, ties by
    player name). No verified attempt: {} (the pool goes back to its funders). An unknown kind raises ValueError.
    Attempts are read in the order given (the order they were submitted): an attempt whose artifact_hash an earlier
    attempt of another player already had earns nothing (the same file under a second name is not a second attempt);
    with normalized_hash (what attempt() returns), a copy that differs only in comments, spacing or docstrings is the
    same file."""
    if isinstance(pool_units, bool) or not isinstance(pool_units, int) or pool_units < 0:
        raise ValueError("pool_units: a whole number from 0")
    best: dict = {}
    first: dict = {}                 # an identical artifact (same artifact_hash) counts only for its first submitter
    for a in attempts:
        if not isinstance(a, dict):
            raise ValueError("each attempt is a dict with player, kind, verified and score")
        _kind(a.get("kind"))
        score = a.get("score")
        if a.get("verified") is not True or isinstance(score, bool) or not isinstance(score, (int, float)) or score != score or not score > 0:
            continue
        who = a.get("player")
        h = a.get("normalized_hash") or a.get("artifact_hash")
        if h is not None and first.setdefault(h, who) != who:
            continue
        best[who] = max(best.get(who, 0), score)
    if not best:
        return {}
    from fractions import Fraction
    total = sum(Fraction(s) for s in best.values())
    exact = {p: Fraction(pool_units) * Fraction(s) / total for p, s in best.items()}
    out = {p: int(x) for p, x in exact.items()}
    left = pool_units - sum(out.values())
    for p in sorted(exact, key=lambda q: (-(exact[q] - out[q]), str(q)))[:left]:
        out[p] += 1
    return out


def swhid(content: bytes) -> str:
    """The Software Heritage content id of these bytes: swh:1:cnt: + the git blob sha1 (intrinsic, computed locally)."""
    data = bytes(content)
    return "swh:1:cnt:" + hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def graduation_record(result: dict, *, amount: int, zenodo: dict | None = None) -> dict:
    """The record of a graduated result as Knos Record holds it: what was verified, the Zenodo deposit (a live sandbox
    DOI, or the labelled FIXTURE with no DOI: a DOI is never invented) and Knos's fees on `amount`, read from
    config/fees.yaml (the graduation and payout lines)."""
    from ..money import fees_config
    cfg = fees_config.load()
    z = zenodo or {"mode": "fixture", "label": "FIXTURE (synthetic, not a Zenodo response): no deposit was made", "doi": None}
    return {"spec_hash": result.get("spec_hash"), "passed": bool(result.get("passed")), "artifact_hash": result.get("artifact_hash"),
            "swhid": result.get("swhid"),
            "zenodo": {"mode": z.get("mode"), "doi": z.get("doi"), "label": z.get("label") or ("Zenodo sandbox" if z.get("doi") else "")},
            "fees": {"graduation": cfg.fee("graduation", amount), "graduation_status": cfg.doc["fees"]["graduation"]["status"],
                     "payout": cfg.fee("payout", amount), "payout_status": cfg.doc["fees"]["payout"]["status"], "from": "config/fees.yaml"},
            "amount": amount}


__all__ = ["KINDS", "attempt", "graduation_record", "split_pool", "swhid"]
