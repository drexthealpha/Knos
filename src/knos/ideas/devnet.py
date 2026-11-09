"""Steps 1 and 2 on Solana devnet for three ideas from three different fields, with real API reads and real vault.

    python -m knos.ideas.devnet --wallets DIR --out FILE.json [--fund-from KEYFILE --fund-sol 0.3]

  idea A  biology   (PubMed)              a claim read live from NCBI E-utilities, field from OpenAlex
  idea B  materials (arXiv)               a claim read live from the arXiv API
  idea C  clinical  (ClinicalTrials.gov)  a registered trial read live from the v2 API

For each: the Claim record (step 1, Retraction Watch checked), Knos's demand check (Qloo MOCK until QLOO_API_KEY,
labelled), a pull commitment (10 units at 4 test units each) locked as one knos_pay order per stage on devnet, one
pre-order in the idea's pool, and stage 1's oracle read live, with its evidence hash and the release audience the judge
signs. Idea C's "results posted" stage has a 60-second deadline: the trial has posted no results by then, so the stage
is REFUNDED to the buyer on devnet (anyone may send RefundOrder) while its other stages stay locked.

DIR holds the demo's own devnet keys (payer.json, buyer.json, mint.json; created when missing, never printed). The
payer is funded from --fund-from once (the transfer signature is written to the output). Test money of the demo's
own mint (6 decimals, no freeze authority). Devnet only. Releasing a met stage needs the judge's signed token (GitHub
OIDC from the pinned prove.yml today; V34PAY's verdict path next): it is not faked here; the payout path runs in
LiteSVM in tests/test_ideas_litesvm.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.system_program import CreateAccountParams, TransferParams, create_account, transfer

from .. import chain
from ..settle.v2 import pay
from . import wanted as W
from .http import Fetcher
from .sources import get

UNIT = 1_000_000
MINT_LEN = 82
IDEAS: list[dict[str, Any]] = [
    {"key": "A", "kind": "biology (PubMed)", "ref": "pmid:42806035", "stages": [("not_retracted", 2000), ("referee_pass", 5000), ("lab_qc", 3000)],
     "work": None, "product": "a base editing kit for protein engineering labs"},
    {"key": "B", "kind": "materials (arXiv)", "ref": "arxiv:1606.00335", "stages": [("preprint_posted", 2000), ("journal_published", 3000), ("referee_pass", 5000)],
     "work": None, "product": "longer-lasting perovskite solar panels"},
    {"key": "C", "kind": "clinical (ClinicalTrials.gov)", "ref": "NCT04718792", "stages": [("trial_registered", 2000), ("results_posted", 3000), ("referee_pass", 5000)],
     "work": [30 * 86_400, pay.MIN_WORK, 90 * 86_400], "product": "a psilocybin therapy for alcohol use disorder"},
]


def _key(path: Path) -> Keypair:
    if not path.exists():
        kp = Keypair()
        path.write_text(json.dumps(list(bytes(kp))), encoding="utf-8")
        path.chmod(0o600)
    return Keypair.from_bytes(bytes(json.loads(path.read_text(encoding="utf-8"))))


def _x(sig: str) -> str:
    return f"https://explorer.solana.com/tx/{sig}?cluster=devnet"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.ideas.devnet")
    ap.add_argument("--wallets", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fund-from", type=Path, help="a devnet keypair that funds the payer once")
    ap.add_argument("--fund-sol", type=float, default=0.3)
    a = ap.parse_args(argv)
    led = chain.ledger()
    if "devnet" not in led.url:
        print("devnet only", file=sys.stderr)
        return 2
    a.wallets.mkdir(parents=True, exist_ok=True)
    old = json.loads(a.out.read_text(encoding="utf-8")) if a.out.exists() else {}
    sigs: list[dict] = old.get("signatures", [])
    payer, buyer, mint_kp = _key(a.wallets / "payer.json"), _key(a.wallets / "buyer.json"), _key(a.wallets / "mint.json")
    mint = mint_kp.pubkey()

    def send(step: str, ixs, signer=None, extra=()):
        sig = led.send(ixs, signer or payer, list(extra))
        sigs.append({"step": step, "signature": sig, "explorer": _x(sig)})
        print(step, sig, flush=True)
        return sig

    bal = int(chain.call(led.url, "getBalance", [str(payer.pubkey())])["value"])
    if bal < 50_000_000 and a.fund_from:
        src = _key(a.fund_from)
        sig = led.send([transfer(TransferParams(from_pubkey=src.pubkey(), to_pubkey=payer.pubkey(), lamports=int(a.fund_sol * 1e9)))], src)
        sigs.append({"step": f"fund the demo payer with {a.fund_sol} devnet SOL from {src.pubkey()}", "signature": sig, "explorer": _x(sig)})
        print("fund payer", sig, flush=True)
    if led.account(mint) is None:
        rent = chain.call(led.url, "getMinimumBalanceForRentExemption", [MINT_LEN])
        init = Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer.pubkey()) + b"\x00", [AccountMeta(mint, False, True)])
        send("create the demo's test mint (6 decimals, no freeze authority)",
             [create_account(CreateAccountParams(from_pubkey=payer.pubkey(), to_pubkey=mint, lamports=rent, space=MINT_LEN, owner=pay.TOKEN)), init], extra=[mint_kp])
    toks = {}
    for who, units, sol in ((payer, 100, 0), (buyer, 300, 60_000_000)):
        ata = pay.ata(who.pubkey(), mint)
        toks[str(who.pubkey())] = ata
        if led.account(ata) is None:
            ixs = [pay.create_ata_ix(payer.pubkey(), who.pubkey(), mint),
                   Instruction(pay.TOKEN, bytes([7]) + (units * UNIT).to_bytes(8, "little"),
                               [AccountMeta(mint, False, True), AccountMeta(ata, False, True), AccountMeta(payer.pubkey(), True, False)])]
            if sol:
                ixs.insert(0, transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=who.pubkey(), lamports=sol)))
            send(f"{units} test units to the {'payer' if who is payer else 'buyer'}", ixs)

    f = Fetcher()
    out_ideas = old.get("ideas", {})
    for spec in IDEAS:
        k = spec["key"]
        prev = out_ideas.get(k) or {}
        c = prev.get("claim") or get(spec["ref"], f)                     # step 1: read once; the saved record is what the vault names
        d = prev.get("demand") or W.demand(c, spec["product"])
        p = W.plan(c, units=10, price=4, stages=spec["stages"], stage_work_s=spec["work"], demand_hash=d.get("hash"))
        funded = []
        for part in p["stages"]:
            order = W.address(p, part, buyer.pubkey())
            if led.account(order) is None and not any(s["step"].startswith(f"idea {k}: lock {part}") for s in sigs):
                sig = send(f"idea {k}: lock {part} ({p[part]['oracle']}, {p[part]['amount'] / UNIT:g} test units) of the pull commitment",
                           [W.fund_ix(p, part, buyer.pubkey(), toks[str(buyer.pubkey())], mint)], signer=buyer)
                funded.append({"part": part, "order": str(order), "signature": sig})
        po = W.address(p, "pool", payer.pubkey())
        if led.account(po) is None and not any(s["step"].startswith(f"idea {k}: pre-order") for s in sigs):
            send(f"idea {k}: pre-order (5 test units) in the idea's pool", [W.fund_ix(p, "pool", payer.pubkey(), toks[str(payer.pubkey())], mint, 5 * UNIT)])
        ev = W.check(c, p["stage1"]["oracle"], f)
        rel = W.release_audience(p, "stage1", W.address(p, "stage1", buyer.pubkey()), ev["evidence_hash"]) if ev["met"] else None
        out_ideas[k] = {"kind": spec["kind"], "ref": spec["ref"], "claim": c, "demand": d, "plan": p, "stage1_check": ev, "stage1_release": rel}

    # idea C: the 60-second "results posted" stage, refunded when the trial has posted no results by its deadline
    c3 = out_ideas["C"]
    p3 = c3["plan"]
    order = W.address(p3, "stage2", buyer.pubkey())
    data = led.account(order)
    o = pay.read_order(data) if data is not None else None
    ev2 = W.check(c3["claim"], "results_posted", f)
    c3["stage2_check"] = ev2
    if o is not None and ev2["met"] is False:
        while led.now() <= o.pay_until:
            time.sleep(5)
        try:
            send("idea C: stage2 (results_posted) past its deadline with no results posted: RefundOrder, amount and fee back to the buyer",
                 [W.refund_ix(payer.pubkey(), order, o)])
        except chain.RpcError as e:
            print("refund", e, file=sys.stderr)
    state = {k: W.state(led, v["plan"], str(mint)) for k, v in out_ideas.items()}
    out = {"what": "Knos steps 1-2 (idea in, wanted?) on Solana devnet: three ideas from three fields, real API reads, real money held until the proof passes on the public "
                   "knos_pay program in the demo's own TEST mint (test money, 0 revenue). Demand check: Qloo MOCK (labelled) until QLOO_API_KEY.",
           "cluster": "devnet", "program": str(pay.PAY_ID), "mint": str(mint), "payer": str(payer.pubkey()), "buyer": str(buyer.pubkey()),
           "ideas": out_ideas, "state": state, "signatures": sigs}
    a.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
