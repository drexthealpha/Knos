"""End-to-end PayOrder capacity: N relays, each paying fees from a key of its own, carry M payments to the end.

    python scripts/load_pay.py --relays 4 --orders 40 --simulate               # here: the path, every count; no rate
    python scripts/load_pay.py --relays 4 --tokens pay.json --wallet <keypair>  # the release run, on devnet

`scripts/load.py measure` times FUNDING only (FundOrderWallet takes no token): it never sent PayOrder, so it says
nothing of a payment's whole path. This does. One payment is what a relay does for one pay token: write the token
on chain, verify GitHub's signature (knos_oidc, several transactions), then PayOrder (knos_pay). Each relay has a
fee payer of its own, and a payment always goes to the relay of its part (`knos.settle.v2.relayq.part_of` of the
token's lane, the same partition the relay's workers use): two relays never carry one order, and no two relays pay
from one fee account.

What is recorded, for every run: payments ATTEMPTED (the denominator), paid, refused (with the program's words),
never completed (no answer before the end), transactions sent, fee payers used; per relay the same. A rate is never
printed without its denominator and its failures, and p50, p95 and p99 are given apart, never merged.

--simulate   The committed test builds of knos_oidc and knos_pay in LiteSVM through the tests' own harness
             (tests/_order.py): M orders funded from one Balance, then paid by N relays in turns, each relay with its
             own key and tip account. It checks that every order is paid exactly once, that each relay paid only its
             own part and that no transaction of one relay was paid for by another's key; it counts transactions and
             compute units per payment. The simulator has no leader, no block limit and no other traffic: it gives NO
             rate and no seconds, and its result says so.
--tokens     On a cluster. GitHub alone signs a pay token (knos_pay takes no other signer for an order funded by
             GitHub's token), so the release run collects the pay tokens of orders it funded through the public
             workflows into a file (a JSON list of {"kind": "pay", "jwt": ...}) and hands it here. Each relay's key is
             derived from the wallet's own (as `load.py measure` does: a run that died is swept by the next), lent SOL
             for fees, and swept back at the end. Each payment goes through `knos.proof.ghrelay.relay_one`, the code the
             worker runs. Recorded: seconds from a payment's first submission to its answer, per payment, p50/p95/p99;
             payments confirmed per second over the run (first submission to last answer).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [p for p in (str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")) if p not in sys.path]

from solders.keypair import Keypair  # noqa: E402

from knos.settle.v2 import relayq  # noqa: E402

SEED = 21
LAMPORTS_PER_RELAY = 50_000_000     # SOL lent to each relay key for fees on a cluster (0.05 SOL); swept back at the end


def pct(values: list[float], p: float) -> float | None:
    """The nearest-rank percentile (as scripts/load.py): the smallest value that at least p% of the values do not exceed."""
    import math
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)] if v else None


def spread(values: list[float]) -> dict:
    return {"n": len(values), "p50": pct(values, 50), "p95": pct(values, 95), "p99": pct(values, 99), "max": max(values, default=None)}


def counted(rows: list[dict], relays: int) -> dict:
    """The totals every run reports: attempts first, then each outcome, so no rate stands without its denominator."""
    out: dict = {"attempted": len(rows), "paid": sum(1 for r in rows if r["state"] == "paid"), "refused": sum(1 for r in rows if r["state"] == "refused"),
           "never_completed": sum(1 for r in rows if r["state"] == "never_completed"),
           "already": sum(1 for r in rows if r["state"] == "already")}     # carried by another relay first: counted, never as paid
    out["per_relay"] = [{"relay": i, "attempted": sum(1 for r in rows if r["relay"] == i), "paid": sum(1 for r in rows if r["relay"] == i and r["state"] == "paid")}
                        for i in range(relays)]
    out["first_refusals"] = [r["why"] for r in rows if r["state"] == "refused"][:5]
    return out


# == the simulator =====================================================================================================
def simulate(relays: int, orders: int, seed: int = SEED) -> dict:
    """See the module's words on --simulate."""
    import random

    import load
    from _order import USDC, OrderChain, issue, user
    from solders.pubkey import Pubkey

    from knos.settle.v2 import pay
    load.fast_signer()
    c = OrderChain()
    meter = c.svm = load.Meter(c.svm)
    rng = random.Random(seed)
    home = c.payer
    keys = [Keypair.from_seed(hashlib.sha256(b"knos-load-pay" + seed.to_bytes(4, "little") + i.to_bytes(2, "little")).digest()) for i in range(relays)]
    for k in keys:
        c.svm.airdrop(k.pubkey(), 10_000_000_000)
        c.token_account(k.pubkey(), c.usdc)         # where the relay's tip arrives
    # -- fund: M orders on M repositories from one Balance, by the harness's own relayer (not measured). Each order's
    #    repository has an owner of its own (its pay token says so), so the orders spread over the relays' parts ------
    funded = []
    for i in range(orders):
        meter.phase, meter.order = "fund", i
        repo, num, amount = 900_000 + i, issue(), (5 + rng.randrange(40)) * USDC
        tok = c.fund_token(num, amount, repository_id=repo)
        assert c.send([c.fund_balance_ix(tok, num, repo=repo)]), f"order {i} was not funded: {c.err}"
        address = pay.order_pda(pay.scope_of(repo, num), c.bal)
        funded.append({"i": i, "address": address, "o": c.order(address), "lane": str(7_000 + i)})
    # -- pay: each order by the relay of its part, the relays in turns (one payment of each in flight at a time) -----
    queues: list[list[dict]] = [[] for _ in range(relays)]
    for x in funded:
        queues[relayq.part_of(x["lane"], relays)].append(x)
    rows: list[dict] = []
    while any(queues):
        for r, q in enumerate(queues):
            if not q:
                continue
            x = q.pop(0)
            c.payer = keys[r]                       # this relay's key writes, verifies and pays: its fee account alone
            meter.phase, meter.order = f"pay:{r}", x["i"]
            before = len(meter.rows)
            wallet = Keypair().pubkey()
            payees = [(user(), 10_000, wallet)]
            tok = c.pay_token(x["address"], payees, o=x["o"], repository_owner_id=int(x["lane"]))     # the lane a relay reads from the token
            ok = tok is not None and c.send([c.pay_ix(x["address"], tok, payees, o=x["o"])])
            mine = meter.rows[before:]
            got = c.balance(pay.ata(wallet, c.usdc))
            rows.append({"relay": r, "order": x["i"], "state": "paid" if ok and got == x["o"].amount else "refused", "why": None if ok else str(c.err)[:200],
                         "transactions": len(mine), "cu": sum(m.cu for m in mine), "payers": sorted({str(m.writable[0]) for m in mine})})
    c.payer = home
    out = {"kind": "pay", "cluster": "local simulator (LiteSVM)", "programs": _programs("the committed test builds"),
           "date": datetime.date.today().isoformat(), "seed": seed, "relays": relays, "orders": orders,
           "fixtures": load.fixtures(), "rate": None, "seconds": None,
           "why_no_rate": "the simulator has no leader, no block limit and no other traffic: it proves the path and counts, it times nothing",
           "fee_payers": [str(k.pubkey()) for k in keys], **counted(rows, relays)}
    paid = [r for r in rows if r["state"] == "paid"]
    out["transactions_per_payment"] = spread([float(r["transactions"]) for r in paid])
    out["cu_per_payment"] = spread([float(r["cu"]) for r in paid])
    own = [str(k.pubkey()) for k in keys]
    out["checks"] = {
        "paid_exactly_once": sum(1 for x in funded if c.order(x["address"]) is None) == len(paid) == orders,
        "each_relay_paid_only_its_part": all(relayq.part_of(funded[r["order"]]["lane"], relays) == r["relay"] for r in rows),
        "no_relay_paid_with_anothers_key": all(r["payers"] == [own[r["relay"]]] for r in rows),
        "fee_payers_distinct": len(set(own)) == relays and str(Pubkey.default()) not in own}
    out["ok"] = all(out["checks"].values())
    return out


def _programs(which: str) -> dict:
    """The program ids a run sends to, as this installation names them, and in words which ids they are."""
    from knos.settle.v2 import pay
    return {"knos_pay": str(pay.PAY_ID), "knos_oidc": str(pay.OIDC_ID), "ids": which}


# == a cluster =========================================================================================================
def on_cluster(rpc, wallet: Keypair, relays: int, tokens: list[dict], clock=time.monotonic, ledger=None, relay_one=None,
               lend=None, sweep=None) -> dict:
    """See the module's words on --tokens. `ledger`, `relay_one`, `lend(key)`, `sweep(key)`: the tests' stand-ins."""
    import load

    from knos.proof import ghrelay
    from knos.settle.v2 import relay
    send = relay_one or ghrelay.relay_one
    keys = load.relay_keys(wallet, relays)
    parts: list[list[dict]] = [[] for _ in range(relays)]
    for t in tokens:
        parts[relayq.part_of(relay.lane(str(t["jwt"])), relays)].append(t)
    out = {"kind": "pay", "cluster": "devnet", "programs": _programs("the ids this installation names (public unless KNOS_PROGRAM_IDS says otherwise)"),
           "date": datetime.date.today().isoformat(), "relays": relays, "orders": len(tokens), "wallet": str(wallet.pubkey()),
           "fee_payers": [str(k.pubkey()) for k in keys]}
    lent = [(lend or (lambda k: _lend(rpc, wallet, k)))(k) for k in keys]
    if not all(lent):
        out.update(ok=False, stopped="a relay key was not lent its SOL", **counted([], relays))
        return out
    rows: list[dict] = []

    def one(r: int) -> list[dict]:
        done = []
        for t in parts[r]:
            began = clock()
            try:
                got = send(ledger, keys[r], str(t.get("kind") or "pay"), str(t["jwt"]))
                state = ("already" if got.get("already") else "paid") if got.get("ok") else "refused"
                why = (None if state == "paid" else "the chain showed it done before this relay sent anything: not a payment of this run"
                       if state == "already" else str(got.get("why") or "no reason given")[:200])
            except Exception as e:  # noqa: BLE001 - no answer: counted, never dropped
                state, why = "never_completed", f"{type(e).__name__}: {e}"[:200]
            done.append({"relay": r, "state": state, "why": why, "began": began, "ended": clock()})
        return done
    with ThreadPoolExecutor(max_workers=max(1, relays)) as pool:
        for got in pool.map(one, range(relays)):
            rows += got
    for k in keys:
        (sweep or (lambda key: _sweep(rpc, wallet, key)))(k)
    paid = [r for r in rows if r["state"] == "paid"]
    wall = (max(r["ended"] for r in rows) - min(r["began"] for r in rows)) if rows else 0.0
    out.update(counted(rows, relays))
    out["seconds"] = round(wall, 2)
    out["paid_per_s"] = round(len(paid) / wall, 3) if wall > 0 else None
    out["payment_s"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in spread([r["ended"] - r["began"] for r in paid]).items()}
    out["confirm_s"] = out["payment_s"]         # first submission to its confirmed answer: p50, p95 and p99 apart, and the worst
    out["ok"] = out["paid"] == out["attempted"]
    return out


def _lend(rpc, wallet: Keypair, key: Keypair) -> bool:
    import load
    from solders.system_program import TransferParams, transfer
    return bool(load.Sender(rpc, wallet).send([transfer(TransferParams(from_pubkey=wallet.pubkey(), to_pubkey=key.pubkey(), lamports=LAMPORTS_PER_RELAY))]).ok)


def _sweep(rpc, wallet: Keypair, key: Keypair) -> None:
    import load
    from solders.system_program import TransferParams, transfer
    have = int(rpc.call("getBalance", [str(key.pubkey()), {"commitment": "confirmed"}])["value"])
    if have > 5_000:
        load.Sender(rpc, key).send([transfer(TransferParams(from_pubkey=key.pubkey(), to_pubkey=wallet.pubkey(), lamports=have - 5_000))])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="End-to-end PayOrder capacity with N relays, each with a fee payer of its own.")
    ap.add_argument("--relays", type=int, required=True)
    ap.add_argument("--orders", type=int, default=0, help="--simulate: orders to fund and pay")
    ap.add_argument("--simulate", action="store_true", help="the committed test builds in LiteSVM: the path and its counts, no rate")
    ap.add_argument("--tokens", type=Path, help="a cluster: a JSON list of pay tokens GitHub signed ({kind, jwt} each)")
    ap.add_argument("--wallet", type=Path, help="a cluster: the keypair that lends the relays their SOL")
    ap.add_argument("--out", type=Path, help="write the result here as JSON (default: print it)")
    a = ap.parse_args(argv)
    if a.relays < 1:
        ap.error("--relays is at least 1")
    if a.simulate:
        if a.orders < 1:
            ap.error("--simulate needs --orders M (at least 1)")
        got = simulate(a.relays, a.orders)
    else:
        if not (a.tokens and a.wallet):
            ap.error("give --simulate, or --tokens FILE and --wallet KEYPAIR for a cluster")
        from knos import chain
        import load
        tokens = json.loads(a.tokens.read_text(encoding="utf-8"))
        if not (isinstance(tokens, list) and all(isinstance(t, dict) and isinstance(t.get("jwt"), str) for t in tokens)):
            ap.error("--tokens is a JSON list of {\"kind\": \"pay\", \"jwt\": ...}")
        wallet = Keypair.from_bytes(bytes(json.loads(a.wallet.read_text(encoding="utf-8"))))
        got = on_cluster(load.Rpc(chain.ledger().url), wallet, a.relays, tokens, ledger=chain.ledger())
    text = json.dumps(got, indent=1, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
