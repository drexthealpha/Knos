"""Measure, on devnet, how long Knos's own transactions take from the send to `confirmed` and to `finalized`, and
write docs/finality.json (what the stats page shows as "paid and final in N ms").

    python scripts/alpenglow_latency.py --keypair W.json --anchors 30 `--escrow` 15 [--jsonl rows.jsonl] [--write]

Every transaction is OUR OWN TEST TRAFFIC, labelled so in the rows, in the Record entries and in docs/finality.json:

  record_anchor   a real Knos Record anchor (knos.record.anchoring.anchor over one labelled "experiment" entry each)
  `escrow_fund`     knos_pay FundWallet (4) of 1.00 of our own synthetic test mint on a synthetic issue number, with the
                  shortest deadline the program takes (MIN_WORK = 60 s)
  `escrow_refund`   knos_pay Refund (7) of that job once the cluster's clock is past its deadline

A full knos_pay payout needs a GitHub OIDC token of a signed workflow run, which this script cannot make: funding and
refunding are the vault transactions anyone can send.

Each transaction is signed first, so its signature is known; ONE WebSocket subscribes to it at `confirmed` and at
`finalized` (signatureSubscribe) BEFORE it is sent through the Knos ledger (knos.chain.Ledger._submit: preflight
at the ledger's commitment), then Knos's own wait (knos.chain.wait at the ledger's commitment) runs. Per row:
confirmed_ms and finalized_ms (the RPC's notifications, from the send) and knos_wait_ms (what a Knos user waits).
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402

from knos import chain  # noqa: E402
from knos.platform import finality, priority  # noqa: E402

LABEL = "internal dogfooding: Knos finality measurement, our own devnet test traffic (synthetic test mint, no real money)"
REPO_ID = 1401439243            # drexthealpha/knos-e2e, the owner's test repository
ISSUE_BASE = 932_000_000        # synthetic issue numbers: no such issues exist
WF_REPO, WF_SHA = "drexthealpha/Knos", "96b243f1b1dd5c975a0318dd9709a0da22b98dcd"
MINT_LEN = 82


def _measure(ledger: chain.Ledger, ixs, payer: Keypair, kind: str, signers=(), within: float = 60.0) -> dict:
    tx = chain.sign(list(ixs), payer, list(signers), ledger._blockhash())
    sig = str(tx.signatures[0])
    ws = priority.WS(priority.ws_url(ledger.url), timeout=5.0)
    got: dict[str, tuple[float, int | None, object]] = {}
    subs: dict[int, str] = {}
    try:
        ws.send({"jsonrpc": "2.0", "id": 1, "method": "signatureSubscribe", "params": [sig, {"commitment": "confirmed"}]})
        ws.send({"jsonrpc": "2.0", "id": 2, "method": "signatureSubscribe", "params": [sig, {"commitment": "finalized"}]})
        end = time.monotonic() + 15
        while len(subs) < 2 and time.monotonic() < end:
            try:
                msg = ws.recv()
            except socket.timeout:
                continue
            if msg.get("id") in (1, 2) and "result" in msg:
                subs[int(msg["result"])] = "confirmed" if msg["id"] == 1 else "finalized"
        if len(subs) < 2:
            raise ConnectionError("signatureSubscribe was not acknowledged")
        stop = time.monotonic() + within

        def listen() -> None:
            while len(got) < 2 and time.monotonic() < stop:
                try:
                    msg = ws.recv()
                except socket.timeout:
                    continue
                except OSError:
                    return
                if msg.get("method") == "signatureNotification":
                    p = msg.get("params") or {}
                    which = subs.get(int(p.get("subscription", -1)))
                    res = p.get("result") or {}
                    if which and which not in got:
                        got[which] = (time.monotonic(), (res.get("context") or {}).get("slot"), (res.get("value") or {}).get("err"))

        th = threading.Thread(target=listen, daemon=True)
        th.start()
        t0 = time.monotonic()
        ledger._submit(tx)
        err = None
        try:
            chain.wait(ledger.url, sig, within, ledger.commitment)
        except Exception as why:  # noqa: BLE001 - recorded on the row
            err = f"{type(why).__name__}: {str(why)[:160]}"
        t_knos = time.monotonic()
        th.join(within)
    finally:
        ws.close()
    ms = lambda t: round((t - t0) * 1000)  # noqa: E731
    row = {"kind": kind, "sig": sig, "label": LABEL, "commitment": ledger.commitment,
           "knos_wait_ms": ms(t_knos), "confirmed_ms": ms(got["confirmed"][0]) if "confirmed" in got else None,
           "finalized_ms": ms(got["finalized"][0]) if "finalized" in got else None,
           "slot": (got.get("finalized") or got.get("confirmed") or (0, None, None))[1],
           "err": err or (got.get("finalized") or (0, None, None))[2], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    print(json.dumps(row), flush=True)
    return row


def _mint_ixs(payer: Pubkey, mint: Pubkey, lamports: int, to_ata: Pubkey, units: int):
    from knos.settle.v2 import pay
    init = Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer) + b"\x00", [AccountMeta(mint, False, True)])    # InitializeMint2, 6 dp
    mint_to = Instruction(pay.TOKEN, b"\x07" + units.to_bytes(8, "little"),
                          [AccountMeta(mint, False, True), AccountMeta(to_ata, False, True), AccountMeta(payer, True, False)])
    return [create_account(CreateAccountParams(from_pubkey=payer, to_pubkey=mint, lamports=lamports, space=MINT_LEN, owner=pay.TOKEN)),
            init, pay.create_ata_ix(payer, payer, mint), mint_to]


def escrow(ledger: chain.Ledger, me: Keypair, wallets: Path, n: int, rows: list) -> None:
    from knos.settle.v2 import pay
    mint_file = wallets / "mint.json"
    if mint_file.exists():
        mint_kp = Keypair.from_bytes(bytes(json.loads(mint_file.read_text())))
    else:
        mint_kp = Keypair()
        mint_file.write_text(json.dumps(list(bytes(mint_kp))))
    mint, src = mint_kp.pubkey(), pay.ata(me.pubkey(), mint_kp.pubkey())
    if ledger.account(mint) is None:
        sig = ledger.send(_mint_ixs(me.pubkey(), mint, ledger.rent(MINT_LEN), src, 1_000 * 10**6), me, [mint_kp])
        print(json.dumps({"setup": "mint", "mint": str(mint), "tx": sig}), flush=True)
    terms = json.dumps({"label": LABEL, "synthetic": True}, separators=(",", ":")).encode()
    start = int(time.time())
    issues = [ISSUE_BASE + start % 1_000_000 * 100 + i for i in range(n)]
    for issue in issues:
        ix = pay.fund_wallet_ix(me.pubkey(), src, mint, REPO_ID, issue, 10**6, WF_REPO, WF_SHA, terms, pay.MERGE, 60)
        rows.append(_measure(ledger, [ix], me, "escrow_fund"))
        time.sleep(0.5)
    last = pay.read_job(ledger.account(pay.job_pda(REPO_ID, issues[-1], me.pubkey())))
    while last is not None and ledger.now() <= last.deadline:
        time.sleep(3)
    for issue in issues:
        job = pay.job_pda(REPO_ID, issue, me.pubkey())
        j = pay.read_job(ledger.account(job))
        if j is None:
            continue
        rows.append(_measure(ledger, [pay.refund_ix(me.pubkey(), job, j)], me, "escrow_refund"))
        time.sleep(0.5)


def anchors(ledger: chain.Ledger, me: Keypair, record_root: Path, n: int, rows: list) -> None:
    from solders.compute_budget import set_compute_unit_limit

    from knos.record import anchoring, journal
    record_root.mkdir(parents=True, exist_ok=True)

    def send(memo: str) -> dict:
        row = _measure(ledger, [set_compute_unit_limit(anchoring.MEMO_UNITS), anchoring.memo_instruction(memo, me.pubkey())], me, "record_anchor")
        rows.append(row)
        return {"tx": row["sig"], "signer": str(me.pubkey()), "slot": row["slot"], "commitment": row["commitment"], "final_ms": row["finalized_ms"]}

    for i in range(n):
        journal.append("experiment", {"label": LABEL, "what": "finality measurement run", "run": i, "public_volume": "excluded"}, root=record_root)
        anchoring.anchor(record_root, keypair=me, send=send)
        time.sleep(0.5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keypair", required=True)
    ap.add_argument("--anchors", type=int, default=30)
    ap.add_argument("--escrow", type=int, default=15, help="jobs funded then refunded: two transactions each")
    ap.add_argument("--record-root", default=None)
    ap.add_argument("--jsonl", default=None, help="append each row here")
    ap.add_argument("--write", action="store_true", help="write docs/finality.json from --jsonl")
    ap.add_argument("--url", default=None)
    a = ap.parse_args()
    url = a.url or chain.CLUSTERS["devnet"]
    me = Keypair.from_bytes(bytes(json.loads(Path(a.keypair).read_text())))
    ledger = chain.Ledger(url)
    consensus = finality.detect(url, ledger._consensus_ask())
    print(json.dumps({"consensus": consensus.to_dict(), "commitment": ledger.commitment}), flush=True)
    rows: list = []
    try:
        if a.anchors:
            anchors(ledger, me, Path(a.record_root or Path(a.keypair).parent / "record"), a.anchors, rows)
        if a.escrow:
            escrow(ledger, me, Path(a.keypair).parent, a.escrow, rows)
    finally:
        if a.jsonl:
            with open(a.jsonl, "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
    if a.write and a.jsonl:
        lines = Path(a.jsonl).read_text(encoding="utf-8").splitlines()
        out = {"label": LABEL, "cluster": "devnet", "measured_at": time.strftime("%Y-%m-%d", time.gmtime()),
               "consensus": consensus.to_dict(),
               "what": "send -> finalized (signatureSubscribe notification at finalized, from the sendTransaction call), Knos's own "
                       "labelled test transactions: record_anchor, escrow_fund, escrow_refund (no payout: that needs a GitHub OIDC token)",
               **finality.parse(lines, "finalized_ms"),
               "confirmed": finality.parse(lines, "confirmed_ms")["all"], "knos_wait": finality.parse(lines, "knos_wait_ms")["all"]}
        (ROOT / "docs" / "finality.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
