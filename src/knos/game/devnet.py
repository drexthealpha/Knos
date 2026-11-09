"""The graduation leg of a game on Solana devnet: pre-orders, the referee's three tests, the contributor split, the
record anchor. --game names YOUR game (made with `knos game new` and played): it is used as it is. Only with a folder
holding no game does it build the SYNTHETIC rings example with scripted players (labelled).

The POT of a game is funded and paid by the referee panel's verdict on chain, with the command line, not here:
    knos game panel DIR --m 2 --keys K1,K2,K3 --program <knos_pay 0.3.34 id> --mint MINT
    knos game fund DIR --wallet FILE --amount 10
    knos game finish DIR && knos game pay DIR --referee FILE     (each referee; the m-th signature pays)
The legs below that still replay in LiteSVM (the graduation vault and pre-order release to the contributor split, and
this file's own pot replay) are labelled; they pay on a GitHub-judged order, which a game result has no run for.

    python -m knos.game.devnet --wallets DIR --game DIR --out FILE [--origin https://github.com/drexthealpha/Knos]

DIR holds the demo's own devnet keys (payer.json funded with devnet SOL; the script writes mint.json, funder-1/2.json,
buyer-1/2.json) and is never printed. Steps:

  1. a test mint (6 decimals) and test units to two funders and two buyers
  2. the game is sealed (examples/autoresearch, SYNTHETIC) and the two funders POOL the pot: each funds a private
     knos_pay order on the pot's terms (60-second deadline, so the demo also shows the refund path on devnet)
  3. three players, two rounds: an AI scientist on Nemotron (MOCK without NEBIUS_API_KEY), a second agent (the Claude
     Agent SDK when ANTHROPIC_API_KEY and claude-agent-sdk are present, else any agent behind the command protocol:
     the no-model local agent, labelled), and a synthetic scripted human; then the referee's final verdicts
  4. the pot's split by the verdicts, paid in LiteSVM from the same funder keys (the same order addresses)
  5. two buyers' pre-orders in the result's pre-order pool on devnet; the referee's verdict (works + wanted + makeable)
  6. graduation: the contributor split paid from the milestone vault and the pre-orders in LiteSVM
  7. the permanent record: Knos Record (Sibyl) entries, the winning file's SWHID, a Software Heritage save request
     (live, no key), the Zenodo sandbox deposition (fixture without KNOS_ZENODO_SANDBOX_TOKEN), a devnet anchor
  8. after the deadlines, every devnet order refunded (amount and fee back to its funder or buyer)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / "examples" / "autoresearch"
JUDGE_REPO = 1401439243          # drexthealpha/knos-e2e (the graduation demo's judge repository id)
QUOTE: dict[str, Any] = {"kind": "compute", "supplier": "Nebius Token Factory, Nemotron 3 Super", "unit_cost": 0.0, "quantity": 1,
         "source": "Token Factory model catalog, read 14 Oct 2026 (knos.nebius.sources.PRICE_PER_M); usage of this run's agent calls"}


def explorer(sig: str) -> str:
    return f"https://explorer.solana.com/tx/{sig}?cluster=devnet"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.game.devnet")
    ap.add_argument("--wallets", required=True, type=Path)
    ap.add_argument("--game", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--origin", default=None, help="an https repository URL to ask Software Heritage to archive")
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args(argv)

    from solders.instruction import AccountMeta, Instruction
    from solders.system_program import CreateAccountParams, TransferParams, create_account, transfer

    from .. import chain, graduation
    from ..graduation.devnet import MINT_LEN, UNIT, _key
    from ..nebius import sources
    from ..settle.v2 import pay
    from . import graduate, players, pot
    from .engine import Game

    led = chain.ledger()
    if "devnet" not in led.url:
        print("devnet only", file=sys.stderr)
        return 2
    payer = _key(a.wallets / "payer.json")
    mint_kp = _key(a.wallets / "mint.json")
    funders = [_key(a.wallets / f"funder-{k}.json") for k in (1, 2)]
    buyers = [_key(a.wallets / f"buyer-{k}.json") for k in (1, 2)]
    mint = mint_kp.pubkey()
    out: dict = {"what": "one Knos game round on Solana devnet: real knos_pay and Memo transactions, a test mint of the demo's own, SYNTHETIC data; "
                         "payout legs in LiteSVM (labelled); test money, 0 revenue", "synthetic": True, "cluster": "devnet",
                 "program": str(pay.PAY_ID), "mint": str(mint), "payer": str(payer.pubkey()), "steps": [], "started": _now()}
    sent = out["steps"]

    def send(step: str, ixs, signers=(), fee_payer=None):
        sig = led.send(ixs, fee_payer or payer, list(signers))
        sent.append({"step": step, "signature": sig, "explorer": explorer(sig)})
        print(step, sig, flush=True)
        return sig

    def save():
        a.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")

    # 1. the test mint and test units
    if led.account(mint) is None:
        rent = chain.call(led.url, "getMinimumBalanceForRentExemption", [MINT_LEN])
        init = Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer.pubkey()) + b"\x00", [AccountMeta(mint, False, True)])
        send("create the demo's test mint (6 decimals)", [create_account(CreateAccountParams(from_pubkey=payer.pubkey(), to_pubkey=mint, lamports=rent,
                                                                                             space=MINT_LEN, owner=pay.TOKEN)), init], [mint_kp])
    tok = {}
    for who in [*funders, *buyers]:
        ata = pay.ata(who.pubkey(), mint)
        tok[str(who.pubkey())] = ata
        if led.account(ata) is None:
            send("SOL for fees and rent + 100 test units to a funder or buyer",
                 [transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=who.pubkey(), lamports=25_000_000)),
                  pay.create_ata_ix(payer.pubkey(), who.pubkey(), mint),
                  Instruction(pay.TOKEN, bytes([7]) + (100 * UNIT).to_bytes(8, "little"),
                              [AccountMeta(mint, False, True), AccountMeta(ata, False, True), AccountMeta(payer.pubkey(), True, False)])])

    # 2. the game is sealed; the funders pool the pot
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    own = (a.game / "game.json").exists()          # YOUR game (knos game new ...): played as it is, nothing synthetic added
    if own:
        g = Game.open(a.game)
    else:
        g = Game.create(a.game, TASK, title="Synthetic rings classifier, many attempts at once", field="ml-research", game_id=f"knos-v0334-{stamp}",
                        rules={"rounds": a.rounds, "per_round": 2, "ladder_eta": 0.01, "max_refusals": 2, "identity_required": True})
    out["game"] = {"id": g.s["id"], "spec_hash": g.s["seal"]["spec_hash"], "judge_hash": g.s["seal"]["judge_hash"], "dir": str(a.game)}
    pp = pot.plan(g.s["id"], g.s["seal"]["spec_hash"], JUDGE_REPO, work_s=pay.MIN_WORK)
    out["pot_plan"] = {k: pp[k] for k in ("scope", "terms", "terms_hash", "wf_repo", "wf_sha", "work_s", "rule")}
    pledges: list[dict[str, Any]] = []
    for f, amt in zip(funders, (20 * UNIT, 10 * UNIT)):
        sig = send(f"pot: a funder pools {amt // UNIT} test units (knos_pay private order, 60 s deadline)",
                   [pot.fund_ix(pp, f.pubkey(), tok[str(f.pubkey())], mint, amt)], [], fee_payer=f)
        order = str(pot.order_address(pp, f.pubkey()))
        g.pledge(f"funder {str(f.pubkey())[:6]}", amt, order=order, tx=sig, cluster="devnet", label="synthetic funder, test units")
        pledges.append({"amount": amt, "key": f, "order": order})
    out["pot_state_after_funding"] = pot.state(led, pp, str(mint))
    out["pot_fees"] = pot.fees(sum(p["amount"] for p in pledges))
    save()

    # 3. the players
    if own:
        attempts = [{k: x.get(k) for k in ("n", "pid", "round", "decision", "shown", "rules")} for x in g.s["attempts"]]
    else:
        nem, nem_label = players.nemotron()
        try:
            second, second_label = players.claude_agent()
            second_name, second_kind = "claude-scientist", "agent"
        except players.PlayerUnavailable as why:
            second, second_label = players.command(f"{sys.executable} -m knos.game.local_agent")
            second_label = f"local deterministic agent (no model), over the command protocol; the Claude Agent SDK player did not play: {why}"
            second_name, second_kind = "cli-agent", "agent"
        roster = [("nemotron-scientist", "agent", nem_label[:80], 9_000_001, nem),
                  (second_name, second_kind, second_label[:80], 9_000_002, second),
                  ("ada", "human", players.SyntheticHuman.LABEL, 9_000_003, players.SyntheticHuman())]
        keys = {}
        for name, kind, label, gid, prop in roster:
            keys[name] = (g.join(name, kind=kind, label=label, github_id=gid), prop)
        out["players"] = [{"name": n, "kind": k, "label": lab, "github_id": gid, "synthetic_github_id": True} for n, k, lab, gid, _ in roster]
        out["labels"] = {"nemotron": nem_label, "second_agent": second_label, "human": players.SyntheticHuman.LABEL}
        attempts = []
        for r in range(a.rounds):
            for name, (j, prop) in keys.items():
                for _ in range(2):
                    got = players.play(g, j["player"], prop)
                    attempts.append({"round": r + 1, "player": name, **{k: got.get(k) for k in ("n", "decision", "shown", "rules", "change", "skipped")}})
                    print("attempt", attempts[-1], flush=True)
            g.close_round()
    out["attempts"] = attempts
    out["board"] = g.board()
    final = g.finish()
    out["verdicts"] = final
    split = pot.split(final)
    out["pot_split"] = split
    save()

    # 4. the pot's payout (LiteSVM: same funder keys -> same order addresses as on devnet)
    if split["payable"]:
        pids = {v["player"]: v for v in final["verdicts"]}
        wallets = {pid: _key(a.wallets / f"payee-{pid}.json").pubkey() for pid in pids}
        payees = [(int(g.s["players"][p["player"]]["github_id"]), p["bps"], str(wallets[p["player"]])) for p in split["parts"]]
        out["pot_payout"] = pot.pay_litesvm(ROOT, pp, [{"amount": x["amount"], "key": x["key"]} for x in pledges], payees)
        out["pot_payout"]["devnet_orders"] = [x["order"] for x in pledges]
        g.s["pot"]["split"] = split
        g.save()
    save()

    # 5. pre-orders in the result's pool, then the referee's verdict
    provisional = {"passed": True, "spec_hash": g.s["seal"]["spec_hash"]}       # the pool's scope and terms do not depend on the verdict
    win = g.s["players"].get(final.get("winner") or "", {})
    cs = [{"role": "researcher", "github_id": 9_000_010}, {"role": "agent", "github_id": int(win.get("github_id") or 9_000_001)},
          {"role": "referee", "github_id": 9_000_011}]
    gp = graduation.plan(provisional, claim_id="game-" + g.s["id"], repo_id=JUDGE_REPO, amount=30 * UNIT, contributors=cs,
                         min_buyers=2, min_locked=15 * UNIT, pool_work_s=pay.MIN_WORK)
    for b, amt in zip(buyers, (10 * UNIT, 7 * UNIT)):
        send(f"pre-order: a buyer locks {amt // UNIT} test units against the game's spec (60 s deadline)",
             [graduation.preorder_ix(gp, b.pubkey(), tok[str(b.pubkey())], mint, amt)], [], fee_payer=b)
    pool = graduation.pool(led, gp, str(mint))
    out["preorder_pool"] = pool
    orders = graduation.demand_orders(gp, pool)
    q = quote(None if own else nem.client, sources)
    v = graduate.verdict(g, orders, [q], locked_price=pool["locked"] / UNIT, min_buyers=2, min_locked=15 * UNIT,
                         record_root=g.root / "record")
    out["referee_verdict"] = {k: v[k] for k in ("passed", "failed", "spec_hash", "recorded")}
    out["referee_verdict"]["checks"] = {n: {"passed": c["passed"], "reasons": c["reasons"]} for n, c in v["checks"].items()}
    save()

    # 6. graduation: the split paid from the vault and the pre-orders (LiteSVM)
    if v["passed"]:
        gplan = graduate.plan(g, v, repo_id=JUDGE_REPO, amount=30 * UNIT, contributors_=cs, min_buyers=2, min_locked=15 * UNIT, pool_work_s=pay.MIN_WORK)
        out["graduation_plan"] = {"split": gplan["split"], "escrow_payout_fee": gplan["escrow"]["payout_fee"],
                                  "graduation_fee": gplan["escrow"]["graduation_fee"], "graduation_fee_status": gplan["escrow"]["graduation_fee_status"],
                                  "split_status": gplan["split_status"]}
        ws = [str(_key(a.wallets / f"contributor-{s['role']}.json").pubkey()) for s in gplan["split"]]
        out["graduation_payout"] = graduate.pay_litesvm(ROOT, gplan, ws, [o["amount"] for o in orders])
        # 7. the permanent record
        kp = payer
        out["permanent"] = graduate.permanent(g, v, gplan, payout=out["graduation_payout"], origin_url=a.origin, anchor_keypair=kp)
        an = (out["permanent"].get("anchor") or {})
        if an.get("tx"):
            sent.append({"step": "Knos Record anchor (Merkle root of the game's record, Memo program)", "signature": an["tx"], "explorer": explorer(an["tx"])})
    save()

    # 8. refunds after the deadlines (anyone may send RefundOrder)
    for label_, addr in [("pot order", x["order"]) for x in pledges] + [("pre-order", r["order"]) for r in pool["orders"]]:
        from solders.pubkey import Pubkey
        o_addr = Pubkey.from_string(addr)
        data = led.account(o_addr)
        o = pay.read_order(data) if data is not None else None
        while o is not None and led.now() <= o.pay_until:
            time.sleep(5)
        if o is not None and led.account(o_addr) is not None:
            try:
                send(f"refund of a devnet {label_} after its deadline (amount and fee back)", [graduation.refund_ix(payer.pubkey(), o_addr, o)])
                sent[-1]["order"] = addr
            except chain.RpcError as why:
                sent.append({"step": f"refund of a devnet {label_}: not sent ({str(why)[:120]})", "signature": None})
        if led.account(o_addr) is None and not any(s.get("order") == addr for s in sent):
            for sig, _slot in led.recent(o_addr, 10):           # another relayer may have refunded it first: anyone may
                if any("knos3:refunded" in line for line in led.logs(sig)):
                    sent.append({"step": f"refund of a devnet {label_} after its deadline (amount and fee back), sent by "
                                         f"{led.payer_of(sig)}: anyone may send RefundOrder", "signature": sig, "explorer": explorer(sig), "order": addr})
                    break
    out["finished"] = _now()
    out["record_dir"] = str(g.root / "record")
    save()
    return 0


def quote(client, sources) -> dict:
    """The compute quote the referee's makeable check reads: this run's agent token usage priced from the catalog
    (`client` None when the game was the caller's own and no Nemotron player ran: 0 tokens)."""
    calls = list(getattr(client, "calls", []) or [])
    usage = sum(c.prompt_tokens for c in calls), sum(c.completion_tokens for c in calls)
    live = bool(getattr(client, "live", False))
    return dict(QUOTE, unit_cost=round(sources.token_cost(sources.SUPER, *usage), 6),
                supplier=QUOTE["supplier"] + ("" if live else " (MOCK usage: estimated tokens, no live call)"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    os.environ.setdefault("KNOS_CLUSTER", "devnet")
    sys.exit(main())
