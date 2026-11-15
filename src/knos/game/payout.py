"""The game's pot on chain, paid by the referee panel's verdict (the m-of-n path of the knos_pay panel test build), to PROVEN players only.

    set_panel(game, m, keys, program, mint)   the game's referee panel (m of n ed25519 keys), the knos_pay program
                                              and the mint; fixed once a pledge exists
    fund_ix(game, funder, funder_token, amount, seq=0)   a funder's pledge: a PANEL order in the game's own scope
                                              (topic "knos-game:" + game id, issue 1), terms naming the game's sealed spec
    pot_on_chain(ledger, game)                every order of the game's scope on chain (locked, paid or gone) and the total
    proven(ledger, game, pid)                 whether a player's identity is PROVEN: its GitHub id (or ORCID iD) has a
                                              wallet bound ON CHAIN by knos_pay's own claim (GitHub: a GitHub-signed run of
                                              the pinned claim workflow; ORCID: an ORCID id_token, Bind 8), read from the
                                              program that holds the bindings, and the player's payee is that wallet (or
                                              it signed its join with that wallet). A claimed id with no binding, or with a
                                              binding to someone else's wallet, is not proven.
    payees(ledger, game)                      the pot's split over the referee's final verdicts among PROVEN players only
                                              (knos.game.pot.split), as (id, bps, wallet) for the verdict
    evidence(game)                            sha256 of the canonical final verdicts: what the referees sign over
    sign(referee, game, order, o, rows)       one referee's PASS (or FAIL when no proven player passed)
    verdict_ixs(relayer, game, order, o, rows, signatures)   [ed25519 precompile, PayOrder/RefundOrder with data]

Unproven players play and are ranked; they are never paid. The referee keys are the game operator's: a funder who
also holds them could pay itself, so the panel's holders are named in the game state for every funder to see before
it funds (docs/reference/AGENTS.md).
"""
from __future__ import annotations

import hashlib
import json

from solders.pubkey import Pubkey

from ..settle.v2 import pay
from . import pot as potmod

ISSUE = 1
BINDINGS_PROGRAM = pay.PAY_ID          # where knos_pay's GitHub claims and ORCID binds live (the public program)


class PayoutError(ValueError):
    pass


def _iss():
    import importlib
    return importlib.import_module("knos.proof.issuers")


def topic(game) -> int:
    return _iss().topic_id("knos-game:" + game.s["id"])


def set_panel(game, m: int, keys: list[str], program: str, mint: str) -> dict:
    if game.s["pot"]["pledges"] and game.s["pot"].get("panel"):
        raise PayoutError("the panel is fixed once a pledge exists")
    try:
        ks = [str(Pubkey.from_string(k)) for k in keys]
        prog, mt = str(Pubkey.from_string(program)), str(Pubkey.from_string(mint))
    except ValueError:
        raise PayoutError("keys, program and mint: Solana addresses (base58)") from None
    if len(set(ks)) != len(ks) or not 1 <= m <= len(ks) <= 10:
        raise PayoutError("panel: 1 <= m <= n <= 10 distinct keys")
    with game.lock:
        game.s["pot"]["panel"] = {"m": m, "keys": ks, "program": prog, "mint": mt}
        game.save()
    return game.s["pot"]["panel"]


def panel(game) -> dict:
    p = game.s["pot"].get("panel")
    if not p:
        raise PayoutError("this game has no referee panel yet: knos game panel DIR --m M --keys K1,K2,K3 --program P --mint M")
    return p


def terms(game) -> bytes:
    r = potmod.rule()
    return pay.terms_json({"v": 2, "kind": "game_pot", "game": game.s["id"], "spec_hash": game.s["seal"]["spec_hash"],
                           "split": {"winner_bps": r["winner_bps"], "partial_bps": r["partial_bps"], "max_paid": r["max_paid"],
                                     "to": "proven players only, by the referee's final verdicts"}})


def fund_ix(game, funder: Pubkey, funder_token: Pubkey, amount: int, seq: int = 0, work_s: int = 7 * 86_400):
    p = panel(game)
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < pay.ORDER_MIN_AMOUNT:
        raise PayoutError(f"amount: at least {pay.ORDER_MIN_AMOUNT / 1e6:.2f} (the smallest knos_pay order)")
    return _iss().fund_order_judged_ix(funder, funder_token, Pubkey.from_string(p["mint"]), topic(game), ISSUE, amount, terms(game),
                                       panel=(p["m"], [bytes(Pubkey.from_string(k)) for k in p["keys"]]), work_s=work_s, seq=seq,
                                       program=Pubkey.from_string(p["program"]))


def order_address(game, funder: Pubkey, seq: int = 0) -> Pubkey:
    p = panel(game)
    return pay.order_pda(pay.scope_of(topic(game), ISSUE), funder, seq, Pubkey.from_string(p["program"]))


def pot_on_chain(ledger, game) -> dict:
    """Every order in the game's scope on its program, as the chain has it now: open orders are locked pledges; an
    order the game's state names that is gone was paid or refunded (its last transaction says which)."""
    p = panel(game)
    prog = Pubkey.from_string(p["program"])
    scope = pay.scope_of(topic(game), ISSUE)
    rows, th = [], pay.terms_hash(terms(game))
    for addr, data in ledger.program_accounts(prog, size=pay.ORDER_LEN, memcmp={24: scope}):
        o = pay.read_order(bytes(data))
        if o is None or o.scope != scope:
            continue
        rows.append({"order": str(addr), "funder": str(o.source), "amount": o.amount, "fee": o.fee, "state": o.state,
                     "mint": str(o.mint), "ours": o.terms == th and str(o.mint) == p["mint"]})
    named = {x.get("order") for x in game.s["pot"]["pledges"] if x.get("order")}
    gone = sorted(named - {r["order"] for r in rows})
    locked = [r for r in rows if r["ours"] and r["state"] == "open"]
    return {"program": p["program"], "mint": p["mint"], "orders": rows, "locked": sum(r["amount"] for r in locked),
            "funders": len({r["funder"] for r in locked}), "closed": gone,
            "ignored": [r["order"] for r in rows if not r["ours"]]}


def _id_of(identity: str | None) -> int | None:
    if not identity:
        return None
    kind, _, value = identity.partition(":")
    if kind == "github":
        return int(value)
    if kind == "orcid":
        return _iss().orcid_id(value)
    return None


def proven(ledger, game, pid: str, program: Pubkey = BINDINGS_PROGRAM) -> dict:
    p = game.player(pid)
    uid = _id_of(p.get("identity"))
    if uid is None:
        return {"proven": False, "why": "no GitHub or ORCID identity (a key alone proves nothing about a person)"}
    programs = [program]
    pp = game.s["pot"].get("panel") or {}
    if pp.get("program") and Pubkey.from_string(pp["program"]) != program:
        programs.append(Pubkey.from_string(pp["program"]))      # an ORCID Bind (8) lives where the knos_pay panel test build runs
    b = None
    for prog in programs:
        b = pay.read_bind(ledger.account(pay.bind_pda(uid, prog)))
        if b is not None:
            break
    if b is None:
        return {"proven": False, "why": f"{p['identity']} has no wallet bound on chain ({program}): claimed, not proven"}
    wallet = str(b.wallet)
    if p.get("payee") not in (None, wallet) and p.get("proof_key") != wallet:
        return {"proven": False, "why": f"{p['identity']} is bound to another wallet than this player's payee", "bound": wallet}
    if p.get("payee") is None and p.get("proof_key") != wallet:
        return {"proven": True, "wallet": wallet, "why": "bound on chain; paid to the bound wallet", "id": uid}
    return {"proven": True, "wallet": wallet, "why": "bound on chain to this player's wallet", "id": uid}


def payees(ledger, game, program: Pubkey = BINDINGS_PROGRAM) -> dict:
    final = game.s.get("final")
    if not final:
        raise PayoutError("the game has no verdicts yet: knos game finish DIR")
    proofs = {v["player"]: proven(ledger, game, v["player"], program) for v in final["verdicts"]}
    filt = dict(final, verdicts=[dict(v, eligible=v.get("eligible", True) and proofs[v["player"]]["proven"]) for v in final["verdicts"]])
    s = potmod.split(filt)
    rows = [(proofs[x["player"]]["id"], x["bps"], proofs[x["player"]]["wallet"]) for x in s["parts"]]
    return {"split": s, "proofs": proofs, "payees": rows}


def evidence(game) -> bytes:
    f = game.s.get("final") or {}
    body = {k: f.get(k) for k in ("game", "spec_hash", "judge_hash", "min_lift", "baseline_final", "winner", "passed")}
    body["verdicts"] = [{k: v.get(k) for k in ("player", "attempt", "attempt_sha256", "passed", "lift", "rank")} for v in f.get("verdicts", [])]
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).digest()


def _payees_tx(rows) -> list:
    return [(i, b, Pubkey.from_string(w)) for i, b, w in rows]


def digest(game, order: Pubkey, o, rows) -> bytes:
    p = panel(game)
    return _iss().verdict_digest(order, o, evidence(game), _payees_tx(rows) if rows else "FAIL", Pubkey.from_string(p["program"]))


def sign(referee, game, order: Pubkey, o, rows) -> tuple[bytes, bytes]:
    """One referee's signature over the pot order's verdict: PASS to `rows` (proven payees), FAIL when it is empty."""
    d = digest(game, order, o, rows)
    return bytes(referee.pubkey()), bytes(referee.sign_message(d))


def verdict_ixs(relayer: Pubkey, game, order: Pubkey, o, rows, signatures) -> list:
    iss, p = _iss(), panel(game)
    keys = [bytes(Pubkey.from_string(k)) for k in p["keys"]]
    prog = Pubkey.from_string(p["program"])
    pre = iss.ed25519_ix(signatures, digest(game, order, o, rows))
    if rows:
        return [pre, iss.pay_order_verdict_ix(relayer, order, o, p["m"], keys, evidence(game), _payees_tx(rows), program=prog)]
    return [pre, iss.refund_order_verdict_ix(relayer, order, o, p["m"], keys, evidence(game), program=prog)]


def pot_view(ledger, game, program: Pubkey = BINDINGS_PROGRAM) -> dict:
    """What `knos game pot` shows: the split exactly as the pay path computes it (payees: proven players only) and,
    per player with a verdict, whether it is paid or "plays, not paid" and why. Before the finish: each player's proof."""
    final = game.s.get("final")
    pids = [v["player"] for v in final["verdicts"]] if final else list(game.s["players"])
    proofs = {pid: proven(ledger, game, pid, program) for pid in pids}
    split = potmod.split(dict(final, verdicts=[dict(v, eligible=v.get("eligible", True) and proofs[v["player"]]["proven"])
                                                for v in final["verdicts"]])) if final else None
    paid = {x["player"]: x["bps"] for x in (split or {}).get("parts", [])}
    players = []
    for pid in pids:
        pr = proofs[pid]
        status = (f"paid {paid[pid]} bps" if pid in paid else "proven, no paid place") if pr["proven"] else "plays, not paid"
        players.append({"player": pid, "name": game.player(pid)["name"], "identity": game.player(pid).get("identity"),
                        "proven": pr["proven"], "status": status, "why": pr["why"]})
    return {"split": split, "players": players}

