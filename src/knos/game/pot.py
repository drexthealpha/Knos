"""The game's pot: funders pool money across all attempts, and the referee's final verdicts divide it.

    rule(cfg)                   the division rule from config/fees.yaml (game_pot: the winner's share and the
                                partial-credit share, at most `max_paid` payees: one knos_pay order pays 1 to 4)
    split(final, cfg)           who receives which basis points of every pot order, from the verdicts: the winner gets
                                winner_bps; the partial share goes to the other passing attempts in proportion to their
                                lift (rank order, at most max_paid - 1 of them); the winner alone takes it all when
                                nobody else passed; nobody passed: no split (every order is refunded after its deadline)
    plan(game_id, spec_hash, repo_id, cfg)   the pot's private knos_pay scope, terms and options (no repository, no
                                issue on chain; the salt sha256("knos-game:" + game id) is public, so anyone finds a pot)
    fund_ix(p, funder, token, mint, amount)  the unsigned FundOrderWallet one funder's wallet signs: amount + payout fee
    state(ledger, p, mint)      the pot as the chain has it (only orders on the pot's own terms and mint are counted)
    pay_litesvm(root, p, pledges, payees)    the payout leg replayed in LiteSVM (LABEL): knos_pay pays an order only on
                                a pay token from its judge (a GitHub-signed run of the pinned prove.yml); a game judged by
                                Knos has no GitHub run, so the same orders are funded and paid in the program's test
                                build, exactly as it divides them. The m-of-n referee verdict path runs on the knos_pay
                                panel test build on devnet (knos.game.payout, `knos game pay`)

Fees: the payout fee (live, knos_pay) is on top of each order, paid by the funder; the Knos bounty fee
(fees.bounty_platform, decided) applies to the pot, its on-chain part being that payout fee and the rest invoiced off
chain. Amounts are base units of a 6-decimal mint; on devnet all of it is test money.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from ..money import fees_config

SALT_TAG = b"knos-game:"
LABEL = "LiteSVM (knos_pay test build), not devnet"
POT_WORK = 7 * 86_400


class PotError(ValueError):
    pass


def rule(cfg: fees_config.FeeConfig | None = None) -> dict:
    cfg = cfg or fees_config.load()
    line = cfg.doc.get("game_pot")
    if not isinstance(line, dict):
        raise PotError("config/fees.yaml has no game_pot section")
    w, p, m = line.get("winner_bps"), line.get("partial_bps"), line.get("max_paid")
    if not all(isinstance(x, int) and not isinstance(x, bool) for x in (w, p, m)) or w + p != 10_000 or not 0 < w <= 10_000 or not 1 <= m <= 4:  # type: ignore[operator]  # w, p, m: the all() just tested each is an int
        raise PotError("game_pot: winner_bps + partial_bps = 10000, winner_bps above 0, max_paid 1 to 4")
    return {"winner_bps": w, "partial_bps": p, "max_paid": m, "status": line.get("status"), "fee_line": line.get("fee_line", "bounty_platform")}


def split(final: dict | None, cfg: fees_config.FeeConfig | None = None) -> dict:
    """[{player, bps}] adding up to 10000, winner first; or why nothing is paid."""
    r = rule(cfg)
    if not final:
        return {"payable": False, "why": "the game has no verdicts yet", "parts": [], "rule": r}
    # only players with an identity are paid (knos.game.engine.join): an anonymous player is ranked, never paid
    passing = sorted([v for v in final.get("verdicts", []) if v.get("passed") and v.get("eligible", True)], key=lambda v: v.get("rank", 10 ** 9))
    if not passing:
        return {"payable": False, "why": "no attempt by a player with an identity passed the referee on the final sealed set: every pot order goes back to its funder after its deadline",
                "parts": [], "rule": r}
    winner, rest = passing[0], passing[1:r["max_paid"]]
    if not rest:
        return {"payable": True, "parts": [{"player": winner["player"], "name": winner["name"], "bps": 10_000, "why": "winner (no other paid place)"}], "rule": r}
    weights = [max(1, round(float(v.get("lift") or 0.0) * 1_000_000)) for v in rest]     # lift in millionths: integer arithmetic
    total = sum(weights)
    shares = [max(1, r["partial_bps"] * w // total) for w in weights]
    win = 10_000 - sum(shares)
    parts = [{"player": winner["player"], "name": winner["name"], "bps": win, "why": "winner"}]
    parts += [{"player": v["player"], "name": v["name"], "bps": b, "why": f"partial credit (rank {v.get('rank')}, lift {v.get('lift')})"}
              for v, b in zip(rest, shares)]
    return {"payable": True, "parts": parts, "rule": r}


def amounts(amount: int, parts: list[dict]) -> list[int]:
    """What each part receives of one order of `amount`, exactly as knos_pay divides it (rounded down, the last the rest)."""
    return fees_config.amounts(amount, [p["bps"] for p in parts])


def fees(amount: int, cfg: fees_config.FeeConfig | None = None) -> dict:
    """The fees on a pot of `amount`: the payout fee each order holds on top (on chain), and the whole Knos bounty fee."""
    cfg = cfg or fees_config.load()
    whole = cfg.platform("bounty_platform", amount)
    return {"payout_fee_onchain": cfg.fee("payout", amount), "bounty_platform": whole,
            "said": f"the funders pay the payout fee on top ({cfg.fee('payout', amount) / 1e6:.6f}); the Knos bounty fee is "
                    f"{whole['fee'] / 1e6:.6f}, of which {whole['offchain'] / 1e6:.6f} is invoiced off chain ({whole['status']})"}


def salt(game_id: str) -> bytes:
    return hashlib.sha256(SALT_TAG + game_id.encode()).digest()


def plan(game_id: str, spec_hash: str, repo_id: int, cfg: fees_config.FeeConfig | None = None, *, wf_repo: str = "drexthealpha/Knos",
         wf_sha: str | None = None, work_s: int = POT_WORK) -> dict:
    from ..settle.v2 import pay
    r = rule(cfg)
    if isinstance(repo_id, bool) or not isinstance(repo_id, int) or repo_id <= 0:
        raise PotError("repo_id: the judge repository's GitHub id")
    if not pay.MIN_WORK <= work_s <= pay.MAX_WORK:
        raise PotError(f"work_s: {pay.MIN_WORK} to {pay.MAX_WORK} seconds")
    terms = pay.terms_json({"v": 1, "kind": "game_pot", "game": game_id, "spec_hash": spec_hash,
                            "split": {"winner_bps": r["winner_bps"], "partial_bps": r["partial_bps"], "max_paid": r["max_paid"],
                                      "by": "the Knos referee's final verdicts"}})
    return {"game": game_id, "spec_hash": spec_hash, "repo_id": repo_id, "program": str(pay.PAY_ID), "mode": pay.MERGE,
            "scope": pay.scope_of(repo_id, 0, salt(game_id)).hex(), "options": pay.opts(pay.F_PRIVATE, judge_repo_id=repo_id, salted=True).hex(),
            "terms": terms.decode(), "terms_hash": pay.terms_hash(terms).hex(), "wf_repo": wf_repo, "wf_sha": wf_sha or pay.IDS["claim_sha"],
            "work_s": work_s, "rule": r}


def fund_ix(p: dict, funder, funder_token, mint, amount: int, seq: int = 0, token_program=None):
    from solders.pubkey import Pubkey

    from ..settle.v2 import pay
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < pay.ORDER_MIN_AMOUNT:
        raise PotError(f"amount: at least {pay.ORDER_MIN_AMOUNT / 1e6:.2f} (the smallest knos_pay order)")
    return pay.fund_order_wallet_ix(funder, funder_token, mint, 0, 0, amount, p["wf_repo"], p["wf_sha"], bytes.fromhex(p["terms_hash"]),
                                    mode=p["mode"], work_s=p["work_s"], seq=seq, options=bytes.fromhex(p["options"]),
                                    scope=bytes.fromhex(p["scope"]), token_program=token_program or pay.TOKEN, program=Pubkey.from_string(p["program"]))


def order_address(p: dict, funder, seq: int = 0):
    from solders.pubkey import Pubkey

    from ..settle.v2 import pay
    return pay.order_pda(bytes.fromhex(p["scope"]), funder, seq, Pubkey.from_string(p["program"]))


def state(ledger, p: dict, mint: str) -> dict:
    """The pot's open orders on its own terms and in `mint`; anything else found in its scope is listed, not counted."""
    from solders.pubkey import Pubkey

    from ..settle.v2 import pay
    from .. import graduation
    found = graduation.orders(ledger, bytes.fromhex(p["scope"]), Pubkey.from_string(p["program"]))
    now = ledger.now() if hasattr(ledger, "now") else None
    rows, ignored = [], []
    for a, o in found:
        bad = None
        if o.terms.hex() != p["terms_hash"] or o.mode != p["mode"]:
            bad = "other terms"
        elif not o.flags & pay.F_PRIVATE or o.judge_repo_id != p["repo_id"]:
            bad = "another kind of order or another judge"
        elif o.wf_repo_hash != pay.wf_repo_hash(p["wf_repo"]) or o.wf_sha != p["wf_sha"]:
            bad = "other pinned workflows"
        elif str(o.mint) != str(mint):
            bad = f"mint {o.mint}"
        if bad:
            ignored.append({"order": str(a), "why": bad})
            continue
        rows.append({"order": str(a), "source": str(o.source), "amount": o.amount, "fee": o.fee, "state": o.state,
                     "past_deadline": None if now is None else now > o.pay_until})
    live = [r for r in rows if r["state"] == "open" and not r["past_deadline"]]
    return {"orders": rows, "ignored": ignored, "funders": len({r["source"] for r in live}), "locked": sum(r["amount"] for r in live)}


def pay_litesvm(root, p: dict, pledges: list[dict], payees: list[tuple[int, int, str]]) -> dict:
    """Replay the pot in LiteSVM: each pledge's order funded on the pot's terms (same scope, same funder key when given,
    so the same order address as on devnet) and paid to `payees` [(GitHub id, bps, address)] with a token the test
    build's GitHub key signs. Needs a Knos checkout (tests/_order.py, tests/fixtures/*.so)."""
    from ..nebius.payout import available
    why = available(Path(root))
    if why:
        return {"label": LABEL, "paid": False, "error": why}
    t = str(Path(root) / "tests")
    if t not in sys.path:
        sys.path.insert(0, t)
    from _order import OrderChain  # noqa: PLC0415 - the test harness of a checkout
    from _pay2 import WF_REPO, WF_SHA  # noqa: PLC0415
    from solders.pubkey import Pubkey

    from ..settle.v2 import pay
    c = OrderChain()
    sigs: list[str] = []
    send = c.svm.send_transaction
    def _send(tx):
        sigs.append(str(tx.signatures[0]))
        return send(tx)
    c.svm.send_transaction = _send
    lp = dict(p, wf_repo=WF_REPO, wf_sha=WF_SHA)
    wallets = [(gid, bps, Pubkey.from_string(addr)) for gid, bps, addr in payees]
    for _gid, _bps, w in wallets:
        c.token_account(w, c.usdc)
    out = []
    for k, pl in enumerate(pledges):
        key = pl.get("key")
        who, tok = c.wallet(c.usdc, int(pl["amount"]) + 10_000_000, key=key)
        ix = fund_ix(lp, who.pubkey(), tok, c.usdc, int(pl["amount"]))
        if not c.send([ix], who, tag="game_pot_fund"):
            return {"label": LABEL, "paid": False, "error": f"funding refused: {c.err}"}
        fund_sig = sigs[-1]
        order = order_address(lp, who.pubkey())
        if not c.pay(order, wallets, repository_id=p["repo_id"], tag="game_pot_pay"):
            return {"label": LABEL, "paid": False, "error": f"payment refused: {c.err}"}
        out.append({"funder": str(who.pubkey()), "order": str(order), "amount": int(pl["amount"]), "litesvm_fund_tx": fund_sig,
                    "litesvm_pay_tx": sigs[-1], "order_closed": c.data(order) is None})
    got = [{"github_id": gid, "address": str(w), "received": c.balance(pay.ata(w, c.usdc))} for gid, _b, w in wallets]
    return {"label": LABEL, "paid": True, "orders": out, "payees": got, "mint": str(c.usdc),
            "why_litesvm": "knos_pay pays an order only on its judge's pay token (a GitHub Actions OIDC token from the pinned prove.yml); "
                           "a game judged by the Knos referee has no such run, so the payout is replayed in the program's test build"}
