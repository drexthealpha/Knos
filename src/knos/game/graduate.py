"""Step 6: a verified game result graduates. The referee's three tests, then the money and the permanent record.

    verdict(game, orders, quotes, ...)    Works = the winner's final verdict (sealed final set, both seeds, judge
                                          unchanged); Wanted = the pre-orders locked against the game's spec (the
                                          claim's pre-order pool on chain, knos.graduation.pool -> demand_orders, or the
                                          staged vault's orders); Makeable = sourced cost quotes against the locked
                                          price. knos.referee.verdict: all three, or no.
    plan(game, verdict, ...)              knos.graduation.plan: the milestone vault and pre-order pool of the claim,
                                          and the contributor split of config/fees.yaml (knos.splits): researcher (who
                                          posted the goal), agent (the winning player, person or AI), referee.
    pay_litesvm(root, p, ...)             the vault and each pre-order paid to the split in LiteSVM (LABEL), because
                                          knos_pay pays only on its judge's token (see knos.game.pot).
    permanent(game, ...)                  Knos Record entries (graduation, split, payout) + the Zenodo sandbox DOI
                                          (fixture without a token) + SWHIDs (the winning file's intrinsic id, and a
                                          save-code-now request for the repository) + a devnet anchor of the Record.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .. import graduation, referee
from ..money import fees_config
from . import ids
from .engine import Game, GameError


def works(game: Game) -> referee.Check:
    f = game.s.get("final")
    if not f:
        return referee.Check("works", False, ["the game has no final verdicts"])
    win = next((v for v in f["verdicts"] if v["player"] == f.get("winner")), None)
    if win is None:
        return referee.Check("works", False, ["no attempt passed on the final sealed set"], {"game": game.s["id"]})
    ev = {"game": game.s["id"], "winner": win["player"], "attempt": win["attempt"], "attempt_sha256": win["attempt_sha256"],
          "lift_per_seed": win["lift_per_seed"], "min_lift": f["min_lift"], "judge_unchanged": f["judge_unchanged"],
          "spec_hash": f["spec_hash"], "synthetic": f["synthetic"]}
    ok = win["passed"] and f["judge_unchanged"]
    return referee.Check("works", ok, [] if ok else (win["reasons"] or ["judge drift"]), ev)


def verdict(game: Game, orders: list[dict], quotes: list[dict], *, locked_price: float, min_buyers: int = 1, min_locked: int = 0,
            min_margin: float = 0.0, record_root=None, record: bool = True) -> dict:
    spec = game.s["seal"]["spec_hash"]
    w = works(game)
    d = referee.wanted(orders, min_buyers=min_buyers, min_locked=min_locked, spec_hash=spec)
    m = referee.makeable(quotes, locked_price=locked_price, min_margin=min_margin)
    return referee.verdict(w, d, m, spec_hash=spec, domain=game.s["field"], record_root=record_root, record=record,
                           claim="game-" + game.s["id"])


def contributors(game: Game, *, researcher_id: int, referee_id: int, researcher_address: str | None = None,
                 referee_address: str | None = None) -> list[dict]:
    f = game.s.get("final") or {}
    win = game.s["players"].get(f.get("winner") or "")
    if not win or not win.get("github_id"):
        raise GameError("the winner has no GitHub id: knos_pay names a payee by its GitHub id")
    out = [{"role": "researcher", "github_id": researcher_id, **({"address": researcher_address} if researcher_address else {})},
           {"role": "agent", "github_id": int(win["github_id"]), **({"address": win["payee"]} if win.get("payee") else {})},
           {"role": "referee", "github_id": referee_id, **({"address": referee_address} if referee_address else {})}]
    return out


def plan(game: Game, v: dict, *, repo_id: int, amount: int, contributors_: list[dict], min_buyers: int = 1, min_locked: int = 0,
         wf_sha: str | None = None, cfg: fees_config.FeeConfig | None = None, **kw) -> dict:
    return graduation.plan(v, claim_id="game-" + game.s["id"], repo_id=repo_id, amount=amount, contributors=contributors_,
                           min_buyers=min_buyers, min_locked=min_locked, wf_sha=wf_sha, cfg=cfg, **kw)


def pay_litesvm(root, p: dict, wallets: list[str], preorders: list[int]) -> dict:
    """The milestone vault (funded by one funder) and each pre-order (one buyer each), funded on the plan's terms in
    LiteSVM and paid by a test-build judge token to the split's payees at `wallets` (one per payee, in plan order)."""
    from ..nebius.payout import available
    from .pot import LABEL
    why = available(Path(root))
    if why:
        return {"label": LABEL, "paid": False, "error": why}
    t = str(Path(root) / "tests")
    if t not in sys.path:
        sys.path.insert(0, t)
    from _order import OrderChain  # noqa: PLC0415
    from _pay2 import WF_SHA  # noqa: PLC0415
    from solders.pubkey import Pubkey

    from ..settle.v2 import pay
    lp = dict(p, wf_sha=WF_SHA)
    c = OrderChain()
    sigs: list[str] = []
    send = c.svm.send_transaction
    def _send(tx):
        sigs.append(str(tx.signatures[0]))
        return send(tx)
    c.svm.send_transaction = _send
    ws = [Pubkey.from_string(w) for w in wallets]
    payees = [(i, b, w) for (i, b, _a), w in zip(p["payees"], ws)]
    for w in ws:
        c.token_account(w, c.usdc)
    steps = []
    if not c.send([graduation.escrow_ix(lp, c.funder.pubkey(), c.funder_tok, c.usdc)], c.funder, tag="grad_escrow"):
        return {"label": LABEL, "paid": False, "error": f"funding the milestone hold refused: {c.err}"}
    steps.append({"step": "milestone hold funded", "litesvm_tx": sigs[-1]})
    e = graduation.address(lp, "escrow", c.funder.pubkey())
    if not c.pay(e, payees, repository_id=p["repo_id"], tag="grad_escrow_pay"):
        return {"label": LABEL, "paid": False, "error": f"paying the milestone's held money refused: {c.err}"}
    steps.append({"step": "the milestone's held money paid to the split", "litesvm_tx": sigs[-1]})
    for amt in preorders:
        b, tok = c.wallet(c.usdc, amt + 10_000_000)
        if not c.send([graduation.preorder_ix(lp, b.pubkey(), tok, c.usdc, amt)], b, tag="grad_preorder"):
            return {"label": LABEL, "paid": False, "error": f"pre-order refused: {c.err}"}
        steps.append({"step": f"pre-order of {amt / 1e6:.2f} locked", "litesvm_tx": sigs[-1]})
        o = graduation.address(lp, "pool", b.pubkey())
        if not c.pay(o, payees, repository_id=p["repo_id"], tag="grad_preorder_pay"):
            return {"label": LABEL, "paid": False, "error": f"pre-order release refused: {c.err}"}
        steps.append({"step": "pre-order released to the split on delivery", "litesvm_tx": sigs[-1]})
    got = [{"role": s["role"], "github_id": s["github_id"], "address": str(w), "received": c.balance(pay.ata(w, c.usdc))}
           for s, w in zip(p["split"], ws)]
    return {"label": LABEL, "paid": True, "steps": steps, "payees": got, "total_received": sum(x["received"] for x in got)}


def permanent(game: Game, v: dict, p: dict | None, *, payout: dict | None = None, origin_url: str | None = None,
              swh=ids.swh_save, zenodo=ids.zenodo_deposit, anchor_keypair=None, anchor_send=None, creators=("Knos",)) -> dict:
    """Record the graduation (via the game's Recorder: Knos Record + Sibyl), mint the ids, anchor on devnet."""
    f = game.s["final"] or {}
    win = next((x for x in f.get("verdicts", []) if x["player"] == f.get("winner")), None)
    out: dict = {"game": game.s["id"], "passed": bool(v.get("passed"))}
    if win is None or not v.get("passed"):
        out["why"] = "the verdict did not pass: nothing graduates"
        return out
    src = json.loads((game.root / "attempts" / f"{win['attempt']}.json").read_text(encoding="utf-8"))["files"][game.task.editable]
    data = src.encode()
    out["swhid_content"] = ids.swhid_content(data)
    out["swh_save"] = swh(origin_url) if origin_url else {"mode": "not asked", "why": "no origin url given"}
    md = ids.metadata(f"Knos game {game.s['id']}: {game.s['title']}",
                      f"The attempt the Knos referee verified on sealed data (spec {f['spec_hash'][:16]}). "
                      + ("SYNTHETIC data. " if game.s["synthetic"] else ""), list(creators), ["knos", game.s["field"]])
    out["zenodo"] = zenodo(md, {game.task.editable: data, "verdict.json": json.dumps(f, sort_keys=True).encode()})
    sp = game.s["seal"]["spec_hash"]
    from . import graduation_record
    rec = graduation_record({"spec_hash": sp, "passed": True, "artifact_hash": win["attempt_sha256"], "swhid": out["swhid_content"]},
                            amount=int((p or {}).get("escrow", {}).get("amount", 0)), zenodo=out["zenodo"])
    out["graduation_record"] = rec
    game._event("graduation", {"game": game.s["id"], "spec_hash": sp, "winner": win["player"], "lift": win["lift"],
                               "best_sha256": win["attempt_sha256"], "swhid": rec["swhid"], "zenodo": rec["zenodo"],
                               "fees": rec["fees"], "synthetic": game.s["synthetic"]})
    if p:
        game._event("split", {"game": game.s["id"], "spec_hash": sp, "parts": [{"role": s["role"], "amount": s["amount"]} for s in p["split"]],
                              "cluster": "devnet", "synthetic": game.s["synthetic"]})
    if payout:
        game._event("payout", {"game": game.s["id"], "spec_hash": sp, "label": payout.get("label", ""), "paid": bool(payout.get("paid")),
                               "total": payout.get("total_received", 0), "synthetic": game.s["synthetic"]})
    if game.rec is not None:
        doi = (out["zenodo"] or {}).get("doi")
        if doi:
            game.rec.paper("doi:" + doi, {"title": md["title"], "spec_hash": sp, "sandbox": True})
        game.rec.paper(out["swhid_content"], {"title": md["title"], "content_sha256": ids.hashlib.sha256(data).hexdigest(), "spec_hash": sp})
        save_id = (out["swh_save"] or {}).get("snapshot_swhid")
        if save_id:
            game.rec.paper(save_id, {"origin": origin_url, "spec_hash": sp})
        out["record"] = game.rec.verify()
        if anchor_keypair is not None or anchor_send is not None:
            out["anchor"] = game.rec.anchor(anchor_keypair, anchor_send)
    return out
