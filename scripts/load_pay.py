"""End-to-end PayOrder capacity: N relays, each paying fees from a key of its own, carry M payments to the end.

    python scripts/load_pay.py --relays 4 --orders 40 --simulate               # here: the path, every count; no rate
    python scripts/load_pay.py --relays 4 --tokens pay.json --wallet <keypair>  # the release run, on devnet

`scripts/load.py measure` times FUNDING only (FundOrderWallet takes no token): it never sent PayOrder, so it says
nothing of a payment's whole path. This does. One payment is what a relay does for one pay token: write the token
on chain, verify GitHub's signature (knos_oidc, several transactions), then PayOrder (knos_pay). Each relay has a
fee payer of its own, and a payment always goes to the relay of its part (`knos.settle.v2.relayq.part_of` of the
token's lane, the same partition the relay's workers use): two relays never carry one order, and no two relays pay
from one fee payer. Since 0.3.22 a pay token's lane is its ORDER (`knos.settle.v2.relay.lane`), so the orders of ONE
owner spread over the relays (the run of 8 Oct had one owner's 40 tokens in one lane, so one relay: 0.097 paid a
second), and `--fee-accounts K` has each order's fee go to one of K token accounts of FEE_OWNER
(`knos.settle.v2.pay.fee_account_for`), so the payments do not all write one account.

What is recorded, for every run: payments ATTEMPTED (the denominator), paid, refused (with the program's words),
never completed (no answer before the end), transactions sent, fee payers used; per relay the same. A rate is never
printed without its denominator and its failures, and p50, p95 and p99 are given apart, never merged.

--simulate   The committed test builds of knos_oidc and knos_pay in LiteSVM through the tests' own harness
             (tests/_order.py): M orders of ONE owner funded from one Balance, then paid by N relays in turns, each
             relay with its own key and tip account, each order's fee to its one of K fee accounts (made first, as
             `knos relay fee-accounts --execute` makes them). It checks that every order is paid exactly once, that
             each relay paid only its own part, that no transaction of one relay was paid for by another's key, that
             the one owner's orders went to more than one relay, and that each fee reached the account its order
             names; it counts transactions and compute units per payment. The simulator has no leader, no block limit and no other traffic: it gives NO
             rate and no seconds, and its result says so.
--tokens     On a cluster. GitHub alone signs a pay token (knos_pay takes no other signer for an order funded by
             GitHub's token), so the release run collects the pay tokens of orders it funded through the public
             workflows into a file (a JSON list of {"kind": "pay", "jwt": ...}) and hands it here. Each relay's key is
             derived from the wallet's own (as `load.py measure` does: a run that died is swept by the next), lent SOL
             for fees, and swept back at the end. Each payment goes through `knos.proof.ghrelay.relay_one`, the code the
             worker runs. Recorded: seconds from a payment's first submission to its answer, per payment, p50/p95/p99;
             payments confirmed per second over the run (first submission to last answer).
--scenario S  contention added to the same run, in the simulator and on a cluster alike (SCENARIOS says each):
             hot-funder (one funder's orders, ONE fee account, all relays at once), rpc-faults (sends refused or their
             answers lost, by a seeded draw, then retried; a payment is counted only when the chain shows it), priority-
             fee (SetComputeUnitPrice on every transaction with room; in the simulator on every other PayOrder, so the
             difference in lamports is the priority fee alone; a v1 transaction carries the same lamports in its message),
             burst (each relay sends all its payments at once; after a 429 or an expired blockhash a payment waits,
             BACKOFF with jitter, and is sent again over a fresh blockhash, BURST_ATTEMPTS sends at most; a resend the
             chain refuses because the first landed is a duplicate refused, not a failure; in the simulator every token
             is verified and open before the first PayOrder). On a cluster each signed transaction of a burst goes
             through knos.settle.v2.fanout.FanLedger: sent to the configured endpoint and to every --second-rpc
             (KNOS_RPC_SECOND), the same bytes again every 2 s until an endpoint takes them, confirmed by its
             signature's status, read in one request for every transaction the run waits on; a dropped
             connection, a timeout or HTTP 408 is no answer, and the payment is sent again (0.3.24: 22 of 40 paid, the
             other 18 lost to exactly these, each after ONE send). Sources for the fee: Solana's fee
             structure, https://solana.com/docs/core/fees/fee-structure (prioritization fee = ceil(price x limit /
             1,000,000) lamports).
--fee-accounts K   fee accounts per mint (default 1: the associated one alone). On a cluster the wallet is their base:
             make them first with `KNOS_RELAY_KEY=<the wallet> knos relay fee-accounts --k K --execute`; a relay that
             finds one missing names the associated one, and the run's record says how many it used.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [p for p in (str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")) if p not in sys.path]

from solders.keypair import Keypair  # noqa: E402

from knos.settle.v2 import relayq  # noqa: E402

SEED = 21
CU_PRICE = 10_000                   # micro-lamports a compute unit, under --scenario priority-fee (devnet; test SOL)
ATTEMPTS = 4                        # a payment's sends at most, under --scenario rpc-faults: the first and three retries
FAULTS = {"refused": 0.15, "lost": 0.15}    # under rpc-faults, of every submission: refused by the endpoint; sent, answer lost
SCENARIOS = {
    "hot-funder": "every payment is of one funder's orders and writes ONE fee account, all relays at once: the write locks every "
                  "payment shares",
    "rpc-faults": "15% of submissions refused by the endpoint and 15% sent with the answer lost, each payment retried up to 3 "
                  "times; a payment counts as paid only when the chain shows it, and a resend after a lost answer must be refused",
    "priority-fee": "every transaction carries a compute unit price, 10,000 micro-lamports unless --cu-price says otherwise: "
                    "SetComputeUnitPrice in a legacy transaction with room, the same lamports in a v1 transaction's message",
    "burst": "every relay sends all of its payments at once instead of one after another; a payment the endpoint turns away "
             "(HTTP 429) or whose blockhash expired is sent again after a bounded wait with jitter, over a fresh blockhash",
}
BURST_ATTEMPTS = 12                 # a payment's sends at most, under --scenario burst: the first and eleven after a transient refusal
BACKOFF = (1.0, 16.0)               # under burst: the first wait and the longest, in seconds; each wait doubles and is jittered to
                                    # between half and all of it (seeded), so 12 sends wait 127 s at most in all (8 sent 63 s in 0.3.24)
# what says nothing of the payment: a rate limit, an expired blockhash, and (0.3.25) what the public endpoint answered 18
# of 40 payments with on 9 October 2026: a dropped connection, a timeout, HTTP 408 or a 5xx, and a send never confirmed
TRANSIENT = re.compile(r"\b429\b|too many requests|blockhash not found|block ?height exceeded|blockhash (?:has )?expired"
                       r"|HTTP Error 408|request timeout|timed? ?out|HTTP Error 50[0234]|not confirmed|remote end closed|connection (?:reset|refused|aborted)"
                       r"|urlopen error|RemoteDisconnected|ConnectionError|TimeoutError", re.I)
DUPLICATE = re.compile(r"already in use|already been processed|already paid|alreadyprocessed", re.I)
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
           "already": sum(1 for r in rows if r["state"] == "already"),     # carried by another relay first: counted, never as paid
           # a resend of a payment this run's own earlier send landed, which the chain refused (the order's single-use
           # marker) or answered "already": the payment is paid once and the second is a duplicate refused, not a failure
           "duplicates_refused": sum(1 for r in rows if r.get("duplicate"))}
    out["per_relay"] = [{"relay": i, "attempted": sum(1 for r in rows if r["relay"] == i), "paid": sum(1 for r in rows if r["relay"] == i and r["state"] == "paid")}
                        for i in range(relays)]
    out["first_refusals"] = [r["why"] for r in rows if r["state"] == "refused"][:5]
    return out


# == the simulator =====================================================================================================
def simulate(relays: int, orders: int, seed: int = SEED, fee_accounts: int = 1, scenario: str | None = None, cu_price: int = CU_PRICE) -> dict:
    """See the module's words on --simulate and --scenario."""
    import random

    from solders.compute_budget import set_compute_unit_price

    import load
    from _order import OWNER, USDC, OrderChain, user
    from solders.pubkey import Pubkey

    from knos.settle.v2 import pay
    if scenario == "hot-funder":
        fee_accounts = 1
    load.fast_signer()
    # The Balance's owner and each order's issue come from the seed, so the seed alone says where every order lies
    # and so which relay's part it falls in: one seed, one run. (They were drawn anew each run: then 1 run in 32 of
    # 2 relays and 6 orders put every order in one part, and hot-funder had one relay write the fee account, not all.)
    c = OrderChain(owner=Keypair.from_seed(hashlib.sha256(b"knos-load-pay-owner" + seed.to_bytes(4, "little")).digest()))
    meter = c.svm = load.Meter(c.svm)
    rng = random.Random(seed)
    home = c.payer
    keys = [Keypair.from_seed(hashlib.sha256(b"knos-load-pay" + seed.to_bytes(4, "little") + i.to_bytes(2, "little")).digest()) for i in range(relays)]
    for k in keys:
        c.svm.airdrop(k.pubkey(), 10_000_000_000)
        c.token_account(k.pubkey(), c.usdc)         # where the relay's tip arrives
    base = home.pubkey()                            # the K fee accounts, as `knos relay fee-accounts --execute` makes them
    rent = c.svm.minimum_balance_for_rent_exemption(pay.TOKEN_ACCOUNT_LEN)
    for i in range(1, fee_accounts):
        assert c.send(pay.create_fee_account_ixs(base, base, c.usdc, i, rent)), c.err
    every_fee = pay.fee_accounts(c.usdc, pay.TOKEN, fee_accounts, base)
    # -- fund: M orders on M repositories of ONE owner from one Balance, by the harness's own relayer (not measured).
    #    A pay token's lane is its order, so one owner's orders still spread over the relays' parts -------------------
    funded = []
    for i in range(orders):
        meter.phase, meter.order = "fund", i
        repo, num, amount = 900_000 + i, 1_001 + i, (20 + rng.randrange(40)) * USDC     # over 16.67: the fee (0.30%) is more than the 0.05 tip
        tok = c.fund_token(num, amount, repository_id=repo)
        assert c.send([c.fund_balance_ix(tok, num, repo=repo)]), f"order {i} was not funded: {c.err}"
        address = pay.order_pda(pay.scope_of(repo, num), c.bal)
        funded.append({"i": i, "address": address, "o": c.order(address), "lane": f"order:{address}",
                       "fee": pay.fee_account_for(address, c.usdc, pay.TOKEN, fee_accounts, base)})
    # -- pay: each order by the relay of its part, the relays in turns (one payment of each in flight at a time; under
    #    `burst` every token is written and verified before the first PayOrder is sent) -----------------------------
    queues: list[list[dict]] = [[] for _ in range(relays)]
    for x in funded:
        queues[relayq.part_of(x["lane"], relays)].append(x)
    turns: list[tuple[int, dict]] = []
    while any(queues):
        for r, q in enumerate(queues):
            if q:
                turns.append((r, q.pop(0)))
    faults = random.Random(seed + 1)
    rows: list[dict] = []
    tally = {"refused": 0, "lost": 0, "resent_and_refused": 0}

    def prepare(r: int, x: dict) -> None:
        x["wallet"] = Keypair().pubkey()
        c.payer = home
        c.token_account(x["wallet"], c.usdc)        # the payee's account exists: the tip is 0.05 and the rest of the fee is FEE_OWNER's
        c.payer = keys[r]                           # this relay's key writes, verifies and pays: its fee payer alone
        meter.phase, meter.order = f"pay:{r}", x["i"]
        x["before"] = len(meter.rows)
        x["payees"] = [(user(), 10_000, x["wallet"])]
        x["tok"] = c.pay_token(x["address"], x["payees"], o=x["o"], repository_owner_id=OWNER)        # one owner, many orders
        x["prepared"] = len(meter.rows)

    def submit(r: int, x: dict) -> tuple[int, str | None]:
        """PayOrder for one order, through the faults the scenario injects; returns (attempts, why it was refused)."""
        c.payer = keys[r]
        meter.phase, meter.order = f"pay:{r}", x["i"]
        x["fee_had"], x["pay_from"] = c.balance(x["fee"]), len(meter.rows)
        x["lamports_had"] = int(c.svm.get_balance(keys[r].pubkey()) or 0)
        ixs = [c.pay_ix(x["address"], x["tok"], x["payees"], o=x["o"], fee_token=x["fee"])]
        if scenario == "priority-fee" and x["i"] % 2 == 0:       # every other order: the difference is the priority fee alone
            ixs.insert(0, set_compute_unit_price(cu_price))
        attempts, why = 0, None
        while attempts < ATTEMPTS:
            attempts += 1
            roll = faults.random() if scenario == "rpc-faults" else 1.0
            if roll < FAULTS["refused"]:            # the endpoint refused the request: nothing reached the chain
                tally["refused"] += 1
                continue
            lost_before = x.get("lost", False)
            ok = c.send(ixs)
            if lost_before and not ok:
                tally["resent_and_refused"] += 1    # a resend after a lost answer: the program refuses the second PayOrder
            if roll < FAULTS["refused"] + FAULTS["lost"]:   # sent, and the answer lost: the relay does not know; it tries again
                tally["lost"] += 1
                x["lost"] = True
                continue
            why = None if ok else str(c.err)[:200]
            break
        return attempts, why

    def settle(r: int, x: dict, attempts: int, why: str | None) -> None:
        mine = meter.rows[x["before"]:x["prepared"]] + meter.rows[x["pay_from"]:]
        got = c.balance(pay.ata(x["wallet"], c.usdc))
        paid = c.order(x["address"]) is None and got == x["o"].amount     # read back from the chain, whatever the answers said
        x["fee_in"] = c.balance(x["fee"]) - x["fee_had"]
        rows.append({"relay": r, "order": x["i"], "state": "paid" if paid else "refused" if why else "never_completed",
                     "why": None if paid else (why or "every attempt failed"), "attempts": attempts, "payee_got": got,
                     "transactions": len(mine), "cu": sum(m.cu for m in mine), "payers": sorted({str(m.writable[0]) for m in mine}),
                     "pay_writes": sorted({str(w) for m in mine if m.stage == "pay" for w in m.writable}),
                     "lamports": x["lamports_had"] - int(c.svm.get_balance(keys[r].pubkey()) or 0)})

    for r, x in turns:
        prepare(r, x)
        if scenario != "burst":
            settle(r, x, *submit(r, x))
    open_at_once = 0
    if scenario == "burst":                         # every token verified and open, then every PayOrder back to back
        open_at_once = sum(1 for _r, x in turns if x["tok"] is not None and c.svm.get_account(x["tok"]) is not None)
        for r, x in turns:
            settle(r, x, *submit(r, x))
    c.payer = home
    out = {"kind": "pay", "cluster": "local simulator (LiteSVM)", "programs": _programs("the committed test builds"),
           "date": datetime.date.today().isoformat(), "seed": seed, "relays": relays, "orders": orders,
           "fixtures": load.fixtures(), "rate": None, "seconds": None,
           "why_no_rate": "the simulator has no leader, no block limit and no other traffic: it proves the path and counts, it times nothing",
           "fee_payers": [str(k.pubkey()) for k in keys], "lanes": "order", "owners": 1, "fee_accounts": fee_accounts, **counted(rows, relays)}
    paid = [r for r in rows if r["state"] == "paid"]
    out["transactions_per_payment"] = spread([float(r["transactions"]) for r in paid])
    out["cu_per_payment"] = spread([float(r["cu"]) for r in paid])
    own = [str(k.pubkey()) for k in keys]
    out["checks"] = {
        "paid_exactly_once": sum(1 for x in funded if c.order(x["address"]) is None) == len(paid) == orders,
        "each_relay_paid_only_its_part": all(relayq.part_of(funded[r["order"]]["lane"], relays) == r["relay"] for r in rows),
        "no_relay_paid_with_anothers_key": all(r["payers"] == [own[r["relay"]]] for r in rows),
        "fee_payers_distinct": len(set(own)) == relays and str(Pubkey.default()) not in own,
        # the relays used are exactly the parts the one owner's orders fall in (the Balance's address is random, so a
        # small run may by chance fall in one part: the check is the partition, and per_relay shows the spread)
        "one_owner_spread_over_relays": {r["relay"] for r in rows} == {relayq.part_of(x["lane"], relays) for x in funded},
        "each_fee_in_its_orders_account": all(x.get("fee_in", 0) > 0 for x in funded) and all(x["fee"] in every_fee for x in funded)}
    out["fee_accounts_used"] = len({str(x["fee"]) for x in funded})
    out["checks"]["no_payee_paid_twice"] = all(r["payee_got"] <= funded[r["order"]]["o"].amount for r in rows)
    if scenario:
        out["scenario"], out["measures"] = scenario, SCENARIOS[scenario]
        out["retries"] = sum(r["attempts"] - 1 for r in rows)
        out["attempts_per_payment"] = spread([float(r["attempts"]) for r in rows])
        out["first_refusals"] = [r["why"] for r in rows if r["state"] == "refused"][:5]
    if scenario == "rpc-faults":
        out["faults_injected"] = dict(tally)
        out["checks"]["faults_were_injected"] = tally["refused"] > 0 and tally["lost"] > 0
        out["checks"]["every_resend_after_a_lost_answer_refused"] = tally["resent_and_refused"] > 0
    if scenario == "priority-fee":
        expected = -(-cu_price * 1_400_000 // 1_000_000)       # ceil(price x limit / 1,000,000): the harness asks for 1.4M units
        out["cu_price_micro_lamports"], out["priority_lamports_expected"] = cu_price, expected
        priced = {r["lamports"] for r in paid if r["order"] % 2 == 0}
        plain = {r["lamports"] for r in paid if r["order"] % 2 == 1}
        out["lamports_per_payorder"] = {"with_price": sorted(priced), "without": sorted(plain)}
        out["checks"]["priority_fee_charged"] = len(priced) == len(plain) == 1 and min(priced) - min(plain) == expected
    if scenario == "hot-funder":
        common = set.intersection(*[{w for r in rows if r["relay"] == i for w in r["pay_writes"]} for i in range(relays)]) if rows else set()
        out["written_by_every_relay"] = len(common)
        out["checks"]["one_fee_account_written_by_every_relay"] = out["fee_accounts_used"] == 1 and str(funded[0]["fee"]) in common
    if scenario == "burst":
        out["tokens_open_at_once"] = open_at_once
        out["checks"]["every_token_open_before_the_first_payment"] = open_at_once == orders
    out["ok"] = all(out["checks"].values())
    return out


def _programs(which: str) -> dict:
    """The program ids a run sends to, as this installation names them, and in words which ids they are."""
    from knos.settle.v2 import pay
    return {"knos_pay": str(pay.PAY_ID), "knos_oidc": str(pay.OIDC_ID), "ids": which}


# == a cluster =========================================================================================================
def on_cluster(rpc, wallet: Keypair, relays: int, tokens: list[dict], clock=time.monotonic, ledger=None, relay_one=None,
               lend=None, sweep=None, fee_accounts: int = 1, scenario: str | None = None, cu_price: int = CU_PRICE, seed: int = SEED,
               pause=time.sleep, seconds: tuple[str, ...] | None = None) -> dict:
    """See the module's words on --tokens, --fee-accounts and --scenario. `ledger`, `relay_one`, `lend(key)`,
    `sweep(key)`: the tests' stand-ins. With K > 1 the relays read KNOS_FEE_SHARDS=K and KNOS_FEE_BASE=<wallet> for
    the run. `pause(seconds)`: how a wait under burst is waited (the tests' own clock). `seconds`: the second
    endpoints a burst's transactions also go to (default KNOS_RPC_SECOND)."""
    import os

    from knos import chain
    from knos.settle.v2 import fanout
    if scenario == "hot-funder":
        fee_accounts = 1
    fan = None
    # a cluster's own ledger: `chain.ledger()`, which `main` hands over, is a FanLedger itself since 0.3.25, so it is made
    # again here with the run's second endpoints and its pause, and counted (before, only a plain chain.Ledger was: the
    # run went out through chain.ledger()'s fan-out with --second-rpc ignored and no `fanout` in its record). A test's
    # stand-in, a subclass of either, is left as it is
    if scenario == "burst" and type(ledger) in (chain.Ledger, fanout.FanLedger):
        fan = ledger = fanout.FanLedger(ledger.url, ledger.commitment, seconds=tuple(seconds) if seconds is not None else fanout.seconds_from_env(),
                                           sleep=pause)
    shaped = Shaped(ledger, scenario, cu_price, seed) if scenario in ("rpc-faults", "priority-fee") else None
    keep = {n: os.environ.get(n) for n in ("KNOS_FEE_SHARDS", "KNOS_FEE_BASE")}
    if fee_accounts > 1:
        os.environ.update(KNOS_FEE_SHARDS=str(fee_accounts), KNOS_FEE_BASE=str(wallet.pubkey()))
    try:
        got = _on_cluster(rpc, wallet, relays, tokens, clock, shaped or ledger, relay_one, lend, sweep, scenario, seed, pause)
    finally:
        for n, v in keep.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v
    got.update(fee_accounts=fee_accounts, lanes="order", owners=len({_owner(str(t["jwt"])) for t in tokens}))
    if scenario:
        got.update(scenario=scenario, measures=SCENARIOS[scenario])
    if scenario == "burst":
        got["backoff"] = {"sends_at_most": BURST_ATTEMPTS, "first_wait_s": BACKOFF[0], "longest_wait_s": BACKOFF[1], "jitter": "half to all of each wait"}
    if fan is not None:
        got["fanout"] = {"endpoints": len(fan.endpoints()), "second_endpoints": len(fan.seconds), "resend_every_s": fan.resend_every * fanout.POLL_S,
                         "confirm_by": "getSignatureStatuses", "gives_up_after_s": fan.polls * fanout.POLL_S, **fan.asked}
    if shaped is not None:
        got.update(shaped.said())
    if scenario == "hot-funder" and got["owners"] != 1:
        got.update(ok=False, stopped=f"hot-funder needs the tokens of one funder; these came from {got['owners']} owners")
    return got


class Shaped:
    """A ledger as the relay uses it, with what a scenario changes on the way to the cluster.

    rpc-faults     of every send, by a seeded draw: refused by the endpoint before anything is sent (ConnectionError),
                   or sent and its answer lost (TimeoutError after the cluster took it), as FAULTS says
    priority-fee   a legacy transaction with room for it carries SetComputeUnitPrice(cu_price) beside the compute unit
                   limit `knos.chain.message` would add; a v1 transaction carries its price in the message's own
                   configuration (`message_v1_priced`), since a compute budget instruction does nothing there: the
                   same lamports, ceil(price x limit / 1,000,000), that a legacy one pays at that price and limit
    Everything else passes through to the ledger."""

    def __init__(self, ledger, scenario: str | None, cu_price: int = CU_PRICE, seed: int = SEED):
        import random
        import threading
        self.inner, self.scenario, self.cu_price = ledger, scenario, cu_price
        self.rng, self.lock = random.Random(seed + 1), threading.Lock()
        self.counts = {"sends": 0, "refused": 0, "lost": 0, "priced": 0, "no_room": 0}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _draw(self) -> str:
        with self.lock:
            self.counts["sends"] += 1
            if self.scenario != "rpc-faults":
                return "ok"
            roll = self.rng.random()
            kind = "refused" if roll < FAULTS["refused"] else "lost" if roll < FAULTS["refused"] + FAULTS["lost"] else "ok"
            if kind != "ok":
                self.counts[kind] += 1
            return kind

    def _priced(self, ixs, payer, v1: bool) -> list:
        """The instructions with the price beside the limit (a legacy transaction that has room for them; a v1
        transaction always has room: its price goes into the message's configuration, which `_send_v1` signs)."""
        ixs = list(ixs)
        if self.scenario != "priority-fee":
            return ixs
        from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price

        from knos import chain
        ixs = [ix for ix in ixs if not (ix.program_id == chain.COMPUTE_BUDGET and bytes(ix.data)[:1] == b"\x03")]     # one price: ours
        more = ([] if any(ix.program_id == chain.COMPUTE_BUDGET for ix in ixs) else [set_compute_unit_limit(chain.MAX_COMPUTE_UNITS)])
        out = more + [set_compute_unit_price(self.cu_price)] + ixs
        with self.lock:
            if v1:
                self.counts["priced"] += 1
                return out
            if chain.tx_size(out, payer.pubkey()) > chain.MAX_TX_BYTES:
                self.counts["no_room"] += 1
                return ixs
            self.counts["priced"] += 1
        return out

    def _signs_itself(self, v1: bool) -> bool:
        """Whether a v1 transaction is signed here, with its price in the message (`knos.chain.message_v1` leaves a
        compute budget instruction out and sets no price): a cluster's ledger under priority-fee. A stand-in ledger
        without `_submit` is handed the priced instructions as they are."""
        return v1 and self.scenario == "priority-fee" and hasattr(self.inner, "_submit") and hasattr(self.inner, "_blockhash")

    def _send_v1(self, groups, payer, signers) -> list[str]:
        """Each group as one priced v1 transaction over one fresh blockhash, sent, then waited for together."""
        from knos import chain
        blockhash = self.inner._blockhash()
        txs = [sign_v1_priced(g, payer, signers, blockhash) for g in groups]
        sigs = [self.inner._submit(tx) for tx in txs]
        url, commitment = getattr(self.inner, "url", ""), getattr(self.inner, "commitment", "confirmed")
        if len(sigs) == 1:
            chain.wait(url, sigs[0], 60.0, commitment)
        else:
            chain.wait_all(url, sigs, 60.0, commitment)
        return sigs

    def send(self, ixs, payer, signers=None, v1: bool = False) -> str:
        kind = self._draw()
        if kind == "refused":
            raise ConnectionError("injected: the endpoint refused the request; nothing was sent")
        ixs = self._priced(ixs, payer, v1)
        if self._signs_itself(v1):
            sig = self._send_v1([ixs], payer, signers)[0]
        else:
            sig = self.inner.send(ixs, payer, signers, v1=True) if v1 else self.inner.send(ixs, payer, signers)
        if kind == "lost":
            raise TimeoutError("injected: the transaction was sent and its answer lost")
        return sig

    def send_all(self, groups, payer, signers=None, v1: bool = False) -> list:
        kind = self._draw()
        if kind == "refused":
            raise ConnectionError("injected: the endpoint refused the request; nothing was sent")
        groups = [self._priced(g, payer, v1) for g in groups]
        if self._signs_itself(v1):
            sigs = self._send_v1(groups, payer, signers)
        else:
            many = getattr(self.inner, "send_all")
            sigs = list(many(groups, payer, signers, v1=True) if v1 else many(groups, payer, signers))
        if kind == "lost":
            raise TimeoutError("injected: the transactions were sent and their answer lost")
        return sigs

    def said(self) -> dict:
        if self.scenario == "rpc-faults":
            return {"faults_injected": {k: self.counts[k] for k in ("sends", "refused", "lost")}}
        return {"cu_price_micro_lamports": self.cu_price, "priority": {k: self.counts[k] for k in ("priced", "no_room")}}


def message_v1_priced(ixs, payer, blockhash=None):
    """`knos.chain.message_v1`, which since 0.3.24 prices a v1 transaction itself: the compute unit limit and price the
    instructions ask for (SetComputeUnitLimit, SetComputeUnitPrice) go into the message's configuration, the price as
    the TOTAL priority fee in lamports, ceil(price x limit / 1,000,000), which is what a legacy transaction with that
    price and limit pays (https://solana.com/docs/core/fees/fee-structure; https://www.helius.dev/docs/rpc/transaction-v1)."""
    from knos import chain
    return chain.message_v1(ixs, payer, blockhash)


def priority_lamports(price: int, units: int) -> int:
    """The priority fee in lamports of `price` micro-lamports a compute unit over a limit of `units`: ceil(price x
    units / 1,000,000) (https://solana.com/docs/core/fees/fee-structure)."""
    return -(-price * units // 1_000_000)


def sign_v1_priced(ixs, payer: Keypair, signers, blockhash):
    """One v1 transaction of `message_v1_priced`, signed by the fee payer and whoever else must sign."""
    from solders.transaction import VersionedTransaction
    everyone = {bytes(k.pubkey()): k for k in [payer, *(signers or [])]}
    m1 = message_v1_priced(ixs, payer.pubkey(), blockhash)
    return VersionedTransaction(m1, [everyone[bytes(k)] for k in m1.account_keys[:m1.header.num_required_signatures]])


def backoff_s(attempt: int, rng: random.Random) -> float:
    """The wait before send `attempt + 1` under burst: BACKOFF[0] doubled per send already made, at most BACKOFF[1],
    jittered to between half and all of it so the relays that were turned away together do not come back together."""
    full = min(BACKOFF[1], BACKOFF[0] * 2 ** (attempt - 1))
    return full / 2 + rng.random() * full / 2


def transient(why: str) -> bool:
    """A refusal that says nothing of the payment: the endpoint's rate limit, or a blockhash that expired before the
    transaction landed. Sent again over a fresh blockhash, it may well go through."""
    return bool(TRANSIENT.search(why))


def _owner(jwt: str) -> str:
    """The repository owner a token names (unverified), for the record: how many owners the run's tokens came from."""
    import base64
    try:
        body = jwt.split(".")[1]
        return str(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))).get("repository_owner_id"))
    except (IndexError, ValueError, AttributeError):
        return "unknown"


def _on_cluster(rpc, wallet: Keypair, relays: int, tokens: list[dict], clock, ledger, relay_one, lend, sweep, scenario: str | None = None,
                seed: int = SEED, pause=time.sleep) -> dict:
    import load

    from knos.proof import ghrelay
    from knos.settle.v2 import relay
    send = relay_one or ghrelay.relay_one
    keys = load.relay_keys(wallet, relays)
    parts: list[list[dict]] = [[] for _ in range(relays)]
    for t in tokens:
        parts[relayq.part_of(relay.lane(str(t["jwt"])), relays)].append(t)
    out: dict = {"kind": "pay", "cluster": "devnet", "programs": _programs("the ids this installation names (public unless KNOS_PROGRAM_IDS says otherwise)"),
           "date": datetime.date.today().isoformat(), "relays": relays, "orders": len(tokens), "wallet": str(wallet.pubkey()),
           "fee_payers": [str(k.pubkey()) for k in keys]}
    lent = [(lend or (lambda k: _lend(rpc, wallet, k)))(k) for k in keys]
    if not all(lent):
        out.update(ok=False, stopped="a relay key was not lent its SOL", **counted([], relays))
        return out
    rows: list[dict] = []

    tries = ATTEMPTS if scenario == "rpc-faults" else BURST_ATTEMPTS if scenario == "burst" else 1

    def pay_one(r: int, t: dict) -> dict:
        """One token, sent again after a refusal or a lost answer under rpc-faults, and after a rate limit or an expired
        blockhash under burst (a bounded wait with jitter first; the relay signs each send over a fresh blockhash, and
        the intent sent is the same pay token, so a second PayOrder can only be refused). A result that says the chain
        had it done already counts as this run's payment only when one of this run's own sends may have landed it, and
        then the resend is a duplicate refused, never a second payment and never a failure."""
        began, sent, attempts, duplicate = clock(), False, 0, False
        state, why_now = "never_completed", "no attempt"
        why: str | None = why_now
        jitter = random.Random(f"{seed}:{t['jwt']}")
        while attempts < tries:
            attempts += 1
            if attempts > 1 and scenario == "burst":
                pause(backoff_s(attempts - 1, jitter))
            try:
                got = send(ledger, keys[r], str(t.get("kind") or "pay"), str(t["jwt"]))
            except Exception as e:  # noqa: BLE001 - no answer: counted, never dropped
                state, why = "never_completed", f"{type(e).__name__}: {e}"[:200]
                sent = sent or not isinstance(e, ConnectionError)
                if scenario == "burst" and not transient(why):
                    break
                continue
            if got.get("ok"):
                state = "already" if got.get("already") and not sent else "paid"
                duplicate = bool(got.get("already")) and sent
                why = None if state == "paid" else "the chain showed it done before this relay sent anything: not a payment of this run"
            else:
                why_now = str(got.get("why") or "no reason given")[:200]
                state, why = "refused", why_now
                if sent and DUPLICATE.search(why_now):          # this run's earlier send landed: the order's single-use marker refuses the second
                    state, why, duplicate = "paid", None, True
                elif "injected" in why_now:
                    sent = sent or "refused the request" not in why_now
                    continue
                elif scenario == "burst" and transient(why_now):
                    # a 429 may have come while the relay waited for an answer, after the cluster took the transaction; an
                    # expired blockhash means it never landed. Each order is one relay's alone, so "already" after a 429
                    # can only be this run's own send
                    sent = sent or "blockhash" not in why_now.lower()
                    continue
            break
        return {"relay": r, "state": state, "why": why, "began": began, "ended": clock(), "attempts": attempts, "duplicate": duplicate}

    def one(r: int) -> list[dict]:
        if scenario == "burst":                     # all of this relay's payments at once
            with ThreadPoolExecutor(max_workers=max(1, len(parts[r]))) as each:
                return list(each.map(lambda t: pay_one(r, t), parts[r]))
        return [pay_one(r, t) for t in parts[r]]
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
    out["retries"] = sum(r["attempts"] - 1 for r in rows)
    out["failures"] = out["refused"] + out["never_completed"]
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
    ap.add_argument("--fee-accounts", type=int, default=1, metavar="K", help="fee accounts per mint, each order's fee to one (default 1)")
    ap.add_argument("--scenario", choices=tuple(SCENARIOS), help="contention to add: " + "; ".join(f"{k}: {v}" for k, v in SCENARIOS.items()))
    ap.add_argument("--cu-price", type=int, default=CU_PRICE, metavar="MICRO_LAMPORTS", help="--scenario priority-fee: the compute unit price")
    ap.add_argument("--second-rpc", action="append", default=None, metavar="URL",
                    help="--scenario burst on a cluster: a second endpoint each transaction is also sent to (repeatable; default KNOS_RPC_SECOND)")
    ap.add_argument("--out", type=Path, help="write the result here as JSON (default: print it)")
    a = ap.parse_args(argv)
    if a.relays < 1:
        ap.error("--relays is at least 1")
    if not 1 <= a.fee_accounts <= 64:
        ap.error("--fee-accounts is 1..64")
    if a.simulate:
        if a.orders < 1:
            ap.error("--simulate needs --orders M (at least 1)")
        got = simulate(a.relays, a.orders, fee_accounts=a.fee_accounts, scenario=a.scenario, cu_price=a.cu_price)
    else:
        if not (a.tokens and a.wallet):
            ap.error("give --simulate, or --tokens FILE and --wallet KEYPAIR for a cluster")
        from knos import chain
        import load
        tokens = json.loads(a.tokens.read_text(encoding="utf-8"))
        if not (isinstance(tokens, list) and all(isinstance(t, dict) and isinstance(t.get("jwt"), str) for t in tokens)):
            ap.error("--tokens is a JSON list of {\"kind\": \"pay\", \"jwt\": ...}")
        wallet = Keypair.from_bytes(bytes(json.loads(a.wallet.read_text(encoding="utf-8"))))
        got = on_cluster(load.Rpc(chain.ledger().url), wallet, a.relays, tokens, ledger=chain.ledger(), fee_accounts=a.fee_accounts,
                         scenario=a.scenario, cu_price=a.cu_price, seconds=tuple(a.second_rpc) if a.second_rpc else None)
    text = json.dumps(got, indent=1, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
