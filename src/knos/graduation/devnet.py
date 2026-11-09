"""The graduation demo on Solana devnet, with real transactions on the public knos_pay program and SYNTHETIC claims.

    python -m knos.graduation.devnet --wallets DIR --out <file> [--judge-repo ID]

DIR holds the demo's own devnet keys (payer.json; the script writes mint.json, buyer-1.json, buyer-2.json there) and
is never printed. What it does, each step once (a step whose account already exists is not sent again):

  1. a test mint of its own (6 decimals, no freeze authority) and 1,000 test units to the payer: the faucet's test
     USDC needs a GitHub fund token, and Circle's devnet USDC a web faucet, so the demo mints its own TEST money;
  2. claim A (synthetic verdict, passed): the milestone vault funded by the payer, and two buyers' pre-orders in
     the pool (the vault open for 30 days, the pre-orders for 90): they stay on chain, locked, for the dashboard;
  3. claim B (synthetic): one pre-order with a 60-second deadline, then RefundOrder after it: the money and the fee
     go back to the buyer.

The payout of a vault needs a GitHub-signed token from the judge repository's pinned prove.yml (knos_oidc verifies
it on chain): the demo does not fake one. The payout path, split and fee included, runs in LiteSVM against the
program's test build (tests/test_money_graduation.py), and the audience the judge would sign is written to the output.

Signatures are public. Nothing here is revenue: test money on devnet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.system_program import CreateAccountParams, TransferParams, create_account, transfer

from .. import chain
from ..settle.v2 import pay
from . import address, escrow, escrow_ix, pay_audience, plan, pool, preorder_ix, refund_ix

UNIT = 1_000_000
MINT_LEN = 82


def _key(path: Path) -> Keypair:
    if not path.exists():
        kp = Keypair()
        path.write_text(json.dumps(list(bytes(kp))), encoding="utf-8")
        path.chmod(0o600)
    return Keypair.from_bytes(bytes(json.loads(path.read_text(encoding="utf-8"))))


def _verdict(name: str) -> dict:
    return {"passed": True, "synthetic": True, "spec_hash": hashlib.sha256(f"knos-v0329-money-demo:{name}:synthetic".encode()).hexdigest(),
            "checks": {"works": "synthetic", "wanted": "synthetic", "makeable": "synthetic"}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.graduation.devnet")
    ap.add_argument("--wallets", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--judge-repo", type=int, default=1401439243, help="the judge repository's id (default drexthealpha/knos-e2e)")
    a = ap.parse_args(argv)
    led = chain.ledger()
    if "devnet" not in led.url:
        print("devnet only", file=sys.stderr)
        return 2
    payer = _key(a.wallets / "payer.json")
    mint_kp = _key(a.wallets / "mint.json")
    buyers = [_key(a.wallets / f"buyer-{k}.json") for k in (1, 2)]
    mint = mint_kp.pubkey()
    sent: list[dict] = []

    def send(step: str, ixs, signers=()):
        sig = led.send(ixs, payer, list(signers))
        sent.append({"step": step, "signature": sig, "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet"})
        print(step, sig)
        return sig

    if led.account(mint) is None:
        rent = chain.call(led.url, "getMinimumBalanceForRentExemption", [MINT_LEN])
        init = Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer.pubkey()) + b"\x00", [AccountMeta(mint, False, True)])
        send("create the demo's test mint", [create_account(CreateAccountParams(from_pubkey=payer.pubkey(), to_pubkey=mint, lamports=rent,
                                                                                 space=MINT_LEN, owner=pay.TOKEN)), init], [mint_kp])
    accounts = {}
    for who in [payer, *buyers]:
        ata = pay.ata(who.pubkey(), mint)
        accounts[str(who.pubkey())] = ata
        if led.account(ata) is None:
            ixs = [pay.create_ata_ix(payer.pubkey(), who.pubkey(), mint),
                   Instruction(pay.TOKEN, bytes([7]) + (1_000 * UNIT if who is payer else 100 * UNIT).to_bytes(8, "little"),
                               [AccountMeta(mint, False, True), AccountMeta(ata, False, True), AccountMeta(payer.pubkey(), True, False)])]
            if who is not payer:
                ixs.insert(0, transfer(TransferParams(from_pubkey=payer.pubkey(), to_pubkey=who.pubkey(), lamports=30_000_000)))
            send(f"test units to {'the payer' if who is payer else 'a buyer'}", ixs)

    contributors = [{"role": "researcher", "github_id": 1}, {"role": "agent", "github_id": 2}, {"role": "lab", "github_id": 3},
                    {"role": "referee", "github_id": 4}]
    # claim A: vault + two pre-orders, open for 30 days
    pa = plan(_verdict("A"), claim_id="knos-v0329-money-demo-A", repo_id=a.judge_repo, amount=50 * UNIT, contributors=contributors,
              min_buyers=2, min_locked=25 * UNIT)
    e = address(pa, "escrow", payer.pubkey())
    if led.account(e) is None:
        send("claim A: fund the milestone hold (50 test units)", [escrow_ix(pa, payer.pubkey(), accounts[str(payer.pubkey())], mint)])
    for b, amt in zip(buyers, (20 * UNIT, 10 * UNIT)):
        o = address(pa, "pool", b.pubkey())
        if led.account(o) is None:
            sig = led.send([preorder_ix(pa, b.pubkey(), accounts[str(b.pubkey())], mint, amt)], b)
            sent.append({"step": f"claim A: a buyer's pre-order ({amt // UNIT} test units)", "signature": sig,
                         "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet"})
            print("preorder", sig)
    # claim B: a pre-order with a 60-second deadline, refunded after it
    pb = plan(_verdict("B"), claim_id="knos-v0329-money-demo-B", repo_id=a.judge_repo, amount=5 * UNIT, contributors=contributors,
              pool_work_s=pay.MIN_WORK)
    b = buyers[0]
    ob = address(pb, "pool", b.pubkey())
    refunded = any(s["step"].startswith("claim B: refund") for s in _old(a.out))
    if not refunded:
        if led.account(ob) is None:
            sig = led.send([preorder_ix(pb, b.pubkey(), accounts[str(b.pubkey())], mint, 5 * UNIT)], b)
            sent.append({"step": "claim B: a pre-order with a 60 s deadline (5 test units)", "signature": sig,
                         "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet"})
            print("preorder B", sig)
        data = led.account(ob)
        o_b = pay.read_order(data) if data is not None else None
        while o_b is not None and led.now() <= o_b.pay_until:
            time.sleep(5)
        if o_b is not None and led.account(ob) is not None:
            try:
                send("claim B: refund after the deadline (amount and fee back to the buyer)", [refund_ix(payer.pubkey(), ob, o_b)])
            except chain.RpcError:
                pass                    # another relayer refunded it first: anyone may send RefundOrder
        if led.account(ob) is None and not any(s["step"].startswith("claim B: refund") for s in sent):
            for sig, _slot in led.recent(ob, 10):
                if any("knos3:refunded" in line for line in led.logs(sig)):
                    sent.append({"step": "claim B: refund after the deadline (amount and fee back to the buyer), sent by another relayer "
                                         f"({led.payer_of(sig)}): anyone may send RefundOrder", "signature": sig,
                                 "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet"})
                    break

    state_a = {"escrow": escrow(led, pa, str(mint)), "pool": pool(led, pa, str(mint))}
    old = _old(a.out)
    out = {"what": "the MONEY graduation demo on Solana devnet: real transactions on the public knos_pay program, SYNTHETIC claims and verdicts, "
                   "a test mint of the demo's own; test money, 0 revenue",
           "synthetic": True, "cluster": "devnet", "program": str(pay.PAY_ID), "mint": str(mint), "mint_note": "the demo's own test mint (6 decimals, no freeze authority)",
           "read": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "payer": str(payer.pubkey()),
           "claims": {"A": {"plan": pa, "state": state_a,
                            "payout_audience": pay_audience(pa, "escrow", e, "0" * 40, 1),
                            "payout_note": "paid when the judge repository's pinned prove.yml run is signed by GitHub with this audience; not faked here"},
                      "B": {"plan": pb, "order": str(ob), "refunded": led.account(ob) is None}},
           "signatures": old + sent}
    a.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    return 0


def _old(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("signatures", [])
    except (OSError, ValueError):
        return []


if __name__ == "__main__":
    sys.exit(main())
