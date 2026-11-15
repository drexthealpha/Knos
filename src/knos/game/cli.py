"""`knos game ...` (also `python -m knos.game ...`): many attempts at once on one sealed goal.

    knos game new DIR --task TASK_DIR --title T [--field F] [--sealed FILE] [--rounds N] [--per-round N] [--eta X]
    knos game state DIR                        the goal, rules, board, pot, verdicts (what any player may see)
    knos game join DIR NAME [--agent] [--label L] [--payee ADDR] [--github-id N | --orcid ID | --pubkey K --signature S]
                                               -> player id and key (shown once); one player per identity and payee
    knos game submit DIR PLAYER KEY FILE       one attempt, judged now on sealed data
    knos game play DIR PLAYER KEY --agent nemotron|claude|human-synthetic|cmd:<command> [--n N]
                                               an agent player makes N attempts through the same door
    knos game board DIR | round DIR | finish DIR
    knos game pot DIR                          the pot: pledges and the orders locked ON CHAIN, the split by the verdicts
                                               among PROVEN players (config/fees.yaml game_pot)
    knos game panel DIR --m 2 --keys K1,K2,K3 --program ID --mint MINT
                                               the game's referee panel (m of n ed25519 keys) on the knos_pay panel test build (devnet FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4)
    knos game fund DIR --wallet FILE --amount 20 [--seq N] [--days 7]
                                               pool money into the pot: a PANEL order of knos_pay in the game's scope
    knos game pay DIR --referee FILE [--relayer FILE]
                                               one referee's verdict on every open pot order: PASS to the proven winners
                                               (FAIL, a refund, when no proven player passed); the m-th signature pays
    knos game serve DIR [--host H] [--port P]  the web page + JSON API for players
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, sort_keys=True, default=str))


def _agent(spec: str):
    from . import players
    if spec == "nemotron":
        return players.nemotron()
    if spec == "claude":
        return players.claude_agent()
    if spec == "human-synthetic":
        return players.SyntheticHuman(), players.SyntheticHuman.LABEL
    if spec.startswith("cmd:"):
        return players.command(spec[4:])
    raise ValueError("--agent: nemotron, claude, human-synthetic or cmd:<command>")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="knos game", description="A Knos game: people and AI scientists attack one sealed goal (docs/reference/AGENTS.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new")
    s.add_argument("dir")
    s.add_argument("--task", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--field", default="ml-research")
    s.add_argument("--sealed", default=None)
    s.add_argument("--rounds", type=int, default=3)
    s.add_argument("--per-round", type=int, default=3)
    s.add_argument("--eta", type=float, default=0.01)
    s.add_argument("--identity-required", action="store_true", help="refuse players with no identity")
    for name in ("state", "board", "round", "finish", "pot"):
        sub.add_parser(name).add_argument("dir")
    s = sub.add_parser("join")
    s.add_argument("dir")
    s.add_argument("name")
    s.add_argument("--agent", action="store_true", help="the player is an AI agent (default: a person)")
    s.add_argument("--label", default="")
    s.add_argument("--payee", default=None)
    s.add_argument("--github-id", type=int, default=None)
    s.add_argument("--orcid", default=None)
    s.add_argument("--pubkey", default=None, help="an ed25519 key as identity, with --signature of knos-game:<game id>:join:<name>")
    s.add_argument("--signature", default=None)
    s = sub.add_parser("submit")
    for arg in ("dir", "player", "key", "file"):
        s.add_argument(arg)
    s = sub.add_parser("play")
    for arg in ("dir", "player", "key"):
        s.add_argument(arg)
    s.add_argument("--agent", required=True)
    s.add_argument("--n", type=int, default=1)
    s = sub.add_parser("panel")
    s.add_argument("dir")
    s.add_argument("--m", type=int, required=True)
    s.add_argument("--keys", required=True, help="the referees' public keys, comma separated")
    s.add_argument("--program", required=True, help="the knos_pay panel test build id (devnet)")
    s.add_argument("--mint", required=True)
    s = sub.add_parser("fund")
    s.add_argument("dir")
    s.add_argument("--wallet", required=True, help="the funder's keypair file (it signs and pays)")
    s.add_argument("--amount", required=True, help="units of the mint, like 20 or 12.5")
    s.add_argument("--seq", type=int, default=0)
    s.add_argument("--days", type=int, default=7)
    s = sub.add_parser("pay")
    s.add_argument("dir")
    s.add_argument("--referee", required=True, help="this referee's keypair file (one of the panel)")
    s.add_argument("--relayer", default=None, help="the keypair that pays the transaction fee (default: the referee)")
    s = sub.add_parser("serve")
    s.add_argument("dir")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    a = ap.parse_args(argv)

    from .engine import Game, GameError
    try:
        if a.cmd == "new":
            g = Game.create(a.dir, a.task, title=a.title, field=a.field, sealed=a.sealed,
                            rules={"rounds": a.rounds, "per_round": a.per_round, "ladder_eta": a.eta,
                                   "identity_required": a.identity_required})
            _print(g.public())
            return 0
        if a.cmd == "serve":
            from .server import serve
            serve(a.dir, a.host, a.port)
            return 0
        g = Game.open(a.dir)
        if a.cmd == "state":
            _print(g.public())
        elif a.cmd == "board":
            _print({"board": g.board(), "round": g.s["round"], "status": g.s["status"]})
        elif a.cmd == "round":
            _print(g.close_round())
        elif a.cmd == "finish":
            _print(g.finish())
        elif a.cmd == "pot":
            from .. import chain
            from . import payout
            _print(pot_report(g, chain.ledger))
        elif a.cmd == "panel":
            from . import payout
            _print(payout.set_panel(g, a.m, [k for k in a.keys.split(",") if k.strip()], a.program, a.mint))
        elif a.cmd == "fund":
            _print(_fund(g, a))
        elif a.cmd == "pay":
            _print(_pay(g, a))
        elif a.cmd == "join":
            _print(g.join(a.name, kind="agent" if a.agent else "human", label=a.label, payee=a.payee, github_id=a.github_id,
                          orcid=a.orcid, pubkey=a.pubkey, signature=a.signature))
        elif a.cmd == "submit":
            g.check_key(a.player, a.key)
            _print(g.submit(a.player, {g.task.editable: Path(a.file).read_text(encoding="utf-8")}))
        elif a.cmd == "play":
            from . import players
            g.check_key(a.player, a.key)
            proposer, label = _agent(a.agent)
            print(f"agent: {label}", file=sys.stderr)
            _print([players.play(g, a.player, proposer) for _ in range(max(1, a.n))])
        return 0
    except (GameError, ValueError, OSError) as why:
        print(f"knos game: {why}", file=sys.stderr)
        return 2


def pot_report(g, ledger_fn) -> dict:
    """`knos game pot`: the pledges, the orders on chain, and the split exactly as `knos game pay` computes it: only
    PROVEN players (a wallet bound on chain) are paid; every other player is listed as "plays, not paid"."""
    from . import payout, pot
    out = {"pot": g.pot_public(), "fees": pot.fees(g.pot_total()) if g.pot_total() else None}
    try:
        led = ledger_fn()
        view = payout.pot_view(led, g)
        out["split"], out["players"] = view["split"], view["players"]
        if g.s["pot"].get("panel"):
            out["on_chain"] = payout.pot_on_chain(led, g)
    except Exception as why:  # noqa: BLE001 - the RPC: said, not hidden; no split is shown that the chain did not confirm
        out["split"] = None
        out["players"] = [{"player": pid, "name": p["name"], "proven": None, "status": "not checked: the chain could not be read"}
                          for pid, p in g.s["players"].items()]
        out["chain_error"] = f"{type(why).__name__}: {str(why)[:200]}"
    return out


def _units(text: str) -> int:
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValueError("amount: a number like 20 or 12.5") from None
    if d <= 0 or (d * 1_000_000) != (d * 1_000_000).to_integral_value():
        raise ValueError("amount: above 0, at most 6 decimals")
    return int(d * 1_000_000)


def _fund(g, a) -> dict:
    from solders.pubkey import Pubkey

    from .. import chain
    from ..record.anchoring import load_keypair
    from ..settle.v2 import pay
    from . import payout
    p = payout.panel(g)
    led = chain.ledger()
    w = load_keypair(a.wallet)
    mint = Pubkey.from_string(p["mint"])
    ix = payout.fund_ix(g, w.pubkey(), pay.ata(w.pubkey(), mint), _units(a.amount), seq=a.seq, work_s=a.days * 86_400)
    sig = led.send([ix], w)
    order = str(payout.order_address(g, w.pubkey(), a.seq))
    row = g.pledge(f"funder {str(w.pubkey())[:6]}", _units(a.amount), order=order, tx=sig, cluster="devnet")
    return {"pledge": row, "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet", "on_chain": payout.pot_on_chain(led, g)}


def _pay(g, a) -> dict:
    from solders.pubkey import Pubkey

    from .. import chain
    from ..record.anchoring import load_keypair
    from ..settle.v2 import pay
    from . import payout
    p = payout.panel(g)
    if not g.s.get("final"):
        raise ValueError("finish the game first: knos game finish DIR")
    led = chain.ledger()
    ref = load_keypair(a.referee)
    relayer = load_keypair(a.relayer) if a.relayer else ref
    if str(ref.pubkey()) not in p["keys"]:
        raise ValueError("this key is not one of the game's referees")
    mint, prog = Pubkey.from_string(p["mint"]), Pubkey.from_string(p["program"])
    who = payout.payees(led, g)
    rows = who["payees"]
    prep = [pay.create_ata_ix(relayer.pubkey(), o, mint) for o in [pay.FEE_OWNER, relayer.pubkey()] + [Pubkey.from_string(w) for _i, _b, w in rows]]
    led.send(prep, relayer)
    sent = []
    for r in payout.pot_on_chain(led, g)["orders"]:
        if not (r["ours"] and r["state"] == "open"):
            continue
        order = Pubkey.from_string(r["order"])
        o = pay.read_order(led.account(order))
        ixs = payout.verdict_ixs(relayer.pubkey(), g, order, o, rows, [payout.sign(ref, g, order, o, rows)])
        sig = led.send(ixs, relayer, v1=chain.tx_size(ixs, relayer.pubkey()) > chain.MAX_TX_BYTES)
        gone = led.account(order) is None
        sent.append({"order": r["order"], "verdict": "PASS" if rows else "FAIL", "signature": sig, "program": str(prog),
                     "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet",
                     "result": ("paid" if rows else "refunded") if gone else "recorded (more referees must sign)"})
    return {"payees": [{"id": i, "bps": b, "wallet": w} for i, b, w in rows], "proofs": who["proofs"], "verdicts": sent}


def register(app, help_lines: list | None = None) -> None:
    """`knos game` in the knos command (src/knos/cli.py _MODULES row)."""
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("game", "For a repository's workflows", "Many attempts at once: people and AI scientists play one sealed goal; funders pool a pot."))

    def game_(ctx) -> None:
        """A Knos game: one sealed goal, people and AI scientists, one referee, a pooled pot (docs/reference/AGENTS.md)."""
        raise typer.Exit(main(list(ctx.args) or ["--help"]))
    game_.__annotations__["ctx"] = typer.Context       # named here: this module's annotations are text, and typer is not a global
    app.command("game", context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []})(game_)


if __name__ == "__main__":
    sys.exit(main())
