"""Load: many funded orders open at once, every one settled once, and what that costs.

    python scripts/load.py --local 1000 --write                      # here: the simulator, the committed test builds
    python scripts/load.py --devnet 1000 --issuer-key issuer.pem --wallet ~/.config/solana/id.json --write   # at release

Two tiers, written to docs/load.json and rendered into docs/LOAD.md (`--write`; without it the result is printed).

  --local N   The test builds of knos_oidc 2.2 and knos_pay 2.2 (tests/fixtures) in LiteSVM, through the tests' own
              harness. N orders on N repositories are funded from one Balance and are all open at once; then they are
              paid in a shuffled order, every 10th token is sent twice and every 50th again after its order closed.
              At the end: every order paid exactly once, paid + fees + refunds == funded, nothing left in any order's
              account, no single-use marker missing. Every transaction's compute units and bytes are recorded per
              stage, and from those and Solana's limits (LIMITS, sourced in docs/LOAD.md) the time 1,000 orders take on
              a cluster with 1, 4 and 16 relayers is derived. Compute units are exact; cluster time is arithmetic.

  --devnet N  Against a cluster, by the operator. GitHub will not sign N tokens on demand, so a test issuer signs
              them: its RSA key (`--issuer-key`, PEM) is registered as a PRIVATE key of the wallet (knos_oidc's
              RegisterPrivateKey: any wallet, usable at once). What that reaches:
                verify   exercised: N tokens written and verified on chain under that key
                fund     exercised: N orders funded by the wallet (FundOrderWallet takes no token), in a mint the
                         script creates, with the shortest work time
                refund   exercised: each order refunded after its deadline, each token account closed
                pay      NOT exercised. knos_pay takes a token GitHub did not sign in one case only: PayOrder on a
                         PRIVATE order funded from a Balance, under a key registered by the wallet that opened that
                         Balance (programs-v2/knos_pay/src/order_judge.rs `token`). Such an order is funded by
                         FundOrderBalance, which takes GitHub's tokens only, one per order. So no test issuer can
                         fund and pay N orders; PayOrder's cost is measured in the simulator.
                meter    NOT exercised: knos_meter takes GitHub's tokens only (programs-v2/knos_meter/src/gh.rs).
              K senders work side by side with one fee-paying wallet. Recorded per stage: transactions, failures,
              retries, and seconds from the first submission to `finalized` (p50/p95/p99), per transaction and per
              unit (one token, one order). The run is appended to docs/load.json marked `cluster: devnet`.

  measure --relays N --orders M     Throughput MEASURED, for the release run on devnet (0.3.20). N relays work side by
              side, each with a fee payer of its own (derived from the wallet's key, so a run that died can be swept
              again), each funding its share of M orders one after another, as a relay does: a key signs for one
              thing at a time. Twice: `apart`, where no two relays write an account in common, and `shared`, where
              every transaction also writes ONE token account (a transfer of one base unit into it). That account
              stands for the fee account, which every release of a mint writes whoever relays it: Solana schedules
              by the accounts a transaction locks for writing, whatever program writes them. Recorded for each:
              confirmed transactions a second (first submission to last confirmation), retries, failures, seconds to
              confirm, the slots they landed in and the most in one slot. The contention seen is the second against
              the first. Then every order is refunded and each relay's SOL goes back to the wallet (each relay's
              token account of the run's mint stays: its rent is not recovered).
                  python scripts/load.py measure --relays 4 --orders 40 --wallet <keypair> --write     # the release run
                  python scripts/load.py measure --relays 3 --orders 6 --simulate                      # here: the path, no rate
              What it does not send: PayOrder (see `pay` above). The figure is of funding with and without one
              shared writable account, not of payments. docs/LOAD.md keeps it apart from the derived bound.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import math
import random
import re
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from solders.hash import Hash  # noqa: E402
from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from solders.system_program import CreateAccountParams, create_account  # noqa: E402

from knos import chain, fees, terms  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402

JSON, DOC = ROOT / "docs" / "load.json", ROOT / "docs" / "LOAD.md"
SEED = 314
# Solana's limits, as docs/LOAD.md sources them. `block_cu_before`: the block limit until SIMD-0286 raised it.
LIMITS = {"block_cu": 100_000_000, "block_cu_before": 60_000_000, "account_cu": 12_000_000, "tx_cu": chain.MAX_COMPUTE_UNITS,
          "tx_bytes": chain.MAX_TX_BYTES, "slot_s": 0.4}
RELAYERS = (1, 4, 16)
STAGES = ("verify", "fund", "pay")
COMPUTE_BUDGET = Pubkey.from_string("ComputeBudget111111111111111111111111111111")


def pct(values, p: float):
    """The nearest-rank percentile: the smallest value that at least p% of the values do not exceed."""
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)] if v else None


# == the local tier ====================================================================================================
@dataclass
class Row:
    stage: str              # verify | fund | pay | other
    phase: str              # what the driver was doing: fund, pay, replay
    order: int
    ok: bool
    cu: int                 # what the whole transaction consumed, as the runtime reports it
    size: int               # the signed transaction's bytes
    writable: tuple


class Meter:
    """Stands where the harness keeps its LiteSVM and passes everything through, noting of every transaction sent: the
    stage it belongs to, whether it succeeded, the compute units it consumed, its bytes and the accounts it locks for
    writing. The harness builds and sends every instruction; this only watches."""
    def __init__(self, svm):
        self._svm, self.rows, self.phase, self.order = svm, [], "setup", -1

    def __getattr__(self, name):
        return getattr(self._svm, name)

    def send_transaction(self, tx):
        r = self._svm.send_transaction(tx)
        ok = "Failed" not in type(r).__name__
        cu = (r if ok else r.meta()).compute_units_consumed
        m = tx.message
        keys, h = list(m.account_keys), m.header
        signed, n = h.num_required_signatures, len(keys)
        writable = tuple(k for i, k in enumerate(keys) if (i < signed - h.num_readonly_signed_accounts if i < signed
                                                           else i < n - h.num_readonly_unsigned_accounts))
        ix = next(i for i in m.instructions if keys[i.program_id_index] != COMPUTE_BUDGET)
        program, tag = keys[ix.program_id_index], bytes(ix.data)[:1]
        stage = "verify" if program == oidc.OIDC_ID else {b"\x10": "fund", b"\x11": "pay"}.get(tag, "other") if program == pay.PAY_ID else "other"
        self.rows.append(Row(stage, self.phase, self.order, ok, cu() if callable(cu) else cu, len(bytes(tx)), writable))
        return r


def fast_signer() -> None:
    """The harness signs test tokens with Python's own pow, a tenth of a second each. The same key through
    `cryptography` gives the same bytes (PKCS#1 v1.5 is deterministic) in a millisecond, and a thousand orders need
    two thousand tokens. Only the signing changes: the key, the claims and the harness's helpers are as they were."""
    from _settle import SeedKey, signing_key
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    k = signing_key()
    if not isinstance(k, SeedKey) or len(k.primes) != 2 or "sign" in vars(k):
        return
    p, q = k.primes
    d = pow(65537, -1, (p - 1) * (q - 1))
    key = rsa.RSAPrivateNumbers(p, q, d, d % (p - 1), d % (q - 1), pow(q, -1, p), rsa.RSAPublicNumbers(65537, k.n)).private_key()
    slow = type(k).sign
    probe = b"knos load"
    assert key.sign(probe, padding.PKCS1v15(), hashes.SHA256()) == slow(k, probe)
    k.sign = lambda data: key.sign(data, padding.PKCS1v15(), hashes.SHA256())


def fixtures() -> dict:
    return {f: hashlib.sha256((ROOT / "tests" / "fixtures" / f).read_bytes()).hexdigest() for f in ("knos_oidc_v2_test.so", "knos_pay_v2_test.so")}


def stage_stats(rows: list[Row], n: int, roles: dict) -> dict:
    """One stage's successful transactions, grouped by order."""
    per: dict[int, list[Row]] = {}
    for r in rows:
        per.setdefault(r.order, []).append(r)
    cu, txs, size = ([sum(getattr(r, f) for r in g) for g in per.values()] for f in ("cu", "ok", "size"))
    every = set(rows[0].writable).intersection(*(r.writable for r in rows)) if rows else set()
    return {"orders": len(per), "transactions": len(rows), "tx_per_order": {"p50": pct(txs, 50), "max": max(txs)},
            "cu_per_order": {"p50": pct(cu, 50), "p95": pct(cu, 95), "max": max(cu), "mean": round(sum(cu) / n)},
            "cu_per_tx_max": max(r.cu for r in rows), "bytes_per_order": {"p50": pct(size, 50), "max": max(size)},
            "bytes_per_tx_max": max(r.size for r in rows),
            "written_by_every_tx": sorted(roles.get(k, {"role": str(k), "one_per": "?"})["role"] + " (one per " + roles.get(k, {"one_per": "?"})["one_per"] + ")"
                                          for k in every)}


def derive(stages: dict, orders: int = 1000, block_cu: int = LIMITS["block_cu"]) -> dict:
    """What the measured compute units allow on a cluster, by arithmetic. Three ceilings apply to a block: the whole
    block's compute; 12M for the transactions that write one account, so 12M per relayer (its fee-paying account is
    written by everything it sends), 12M for the orders funded from one Balance, and 12M for PayOrder as a whole (every
    one writes the one fee account); and nothing else is in the block. The slowest ceiling sets the number of blocks."""
    acc, slot = LIMITS["account_cu"], LIMITS["slot_s"]
    cu = {s: stages[s]["cu_per_order"]["mean"] for s in STAGES}
    total = sum(cu.values())
    out = {"orders": orders, "block_cu": block_cu, "cu_per_order": total,
           "one_relayer_orders_per_second": round(acc / total / slot, 2),
           "fee_account_orders_per_second": round(acc / cu["pay"] / slot, 1),
           "one_balance_orders_per_second": round(acc / cu["fund"] / slot, 1), "relayers": {}}
    for r in RELAYERS:
        ceilings = {"the block": orders * total / block_cu, "the relayers' own accounts": orders * total / (r * acc),
                    "the Balance": orders * cu["fund"] / acc, "the fee account": orders * cu["pay"] / acc}
        slots = math.ceil(max(ceilings.values()))
        out["relayers"][str(r)] = {"blocks": slots, "seconds": round(slots * slot, 1), "bound_by": max(ceilings, key=ceilings.get),
                                   "orders_per_second": round(orders / (slots * slot), 1), "under_a_minute": slots * slot < 60}
    return out


def run_local(n: int, seed: int = SEED) -> dict:
    from _order import MAINT, OWNER, REPO, USDC, OrderChain, issue, user
    assert MAINT and OWNER
    fast_signer()
    began = time.monotonic()
    c = OrderChain()
    meter = c.svm = Meter(c.svm)
    rng = random.Random(seed)
    me = c.payer.pubkey()
    roles = {me: {"role": "the relayer's own account, which pays the transaction fee", "one_per": "relayer"},
             c.tip: {"role": "the relayer's token account, where its tip arrives", "one_per": "relayer"},
             c.bal: {"role": "the funder's Balance", "one_per": "funder"},
             pay.baltok_pda(c.bal): {"role": "the Balance's token account", "one_per": "funder"},
             pay.balx_pda(c.bal): {"role": "the Balance's side account", "one_per": "funder"},
             c.fee: {"role": "the fee account (FEE_OWNER's token account of the mint)", "one_per": "mint, for every relayer and funder"}}
    baltok = pay.baltok_pda(c.bal)
    start = {"balance": c.balance(baltok), "fee": c.balance(c.fee), "tip": c.balance(c.tip)}

    def refused(ix: Instruction, order: int) -> bool:
        meter.phase, meter.order = "replay", order
        return not c.send([ix])

    # -- fund: n orders, n repositories, one Balance; every 10th fund token sent a second time at once ---------------
    orders, sent_twice, sent_late = [], 0, 0
    for i in range(n):
        meter.phase, meter.order = "fund", i
        repo, num, amount = REPO + 1 + i, issue(), (5 + rng.randrange(40)) * USDC
        tok = c.fund_token(num, amount, repository_id=repo)
        ix = c.fund_balance_ix(tok, num, repo=repo)
        assert c.send([ix]), f"order {i} was not funded: {c.err}"
        address = pay.order_pda(pay.scope_of(repo, num), c.bal)
        o = c.order(address)
        assert o is not None and (o.state, o.amount, o.repo_id, o.issue) == ("open", amount, repo, num), f"order {i} is not as it was funded"
        orders.append({"address": address, "o": o, "fund_ix": ix, "fund_sig": pay.sig_hash(c.data(tok))})
        if i % 10 == 0:
            assert refused(ix, i), f"fund token {i} was accepted twice"
            sent_twice += 1
    after_fund = c.balance(baltok)
    funded = start["balance"] - after_fund
    held = sum(c.held(x["address"]) for x in orders)
    open_at_once = sum(1 for x in orders if (o := c.order(x["address"])) is not None and o.state == "open")
    assert open_at_once == n and held == funded == sum(x["o"].amount + x["o"].fee for x in orders), "the orders do not hold what left the Balance"

    # -- pay: in a shuffled order, one payee or two; every 10th pay token sent a second time at once ------------------
    turn = list(range(n))
    rng.shuffle(turn)
    for j, i in enumerate(turn):
        x = orders[i]
        meter.phase, meter.order = "pay", i
        wallets = [Keypair().pubkey() for _ in range(2 if i % 5 == 0 else 1)]
        payees = [(user(), 10_000 // len(wallets), w) for w in wallets]
        tok = c.pay_token(x["address"], payees, o=x["o"])
        ix = c.pay_ix(x["address"], tok, payees, o=x["o"])
        assert c.send([ix]), f"order {i} was not paid: {c.err}"
        x.update(wallets=wallets, pay_ix=ix, pay_sig=pay.sig_hash(c.data(tok)))
        if j % 10 == 0:
            assert refused(ix, i), f"pay token {i} was accepted twice"
            sent_twice += 1
    # -- every 50th token again, now that its order is closed: a fund token would fund it anew, a pay token pay it ----
    for i in range(0, n, 50):
        for ix in (orders[i]["pay_ix"], orders[i]["fund_ix"], orders[i]["pay_ix"]):
            assert refused(ix, i), f"a token of order {i} was accepted after the order closed"
            sent_late += 1

    # -- the invariants ----------------------------------------------------------------------------------------------
    got = [sum(c.balance(pay.ata(w, c.usdc)) for w in x["wallets"]) for x in orders]
    once = sum(1 for x, g in zip(orders, got) if g == x["o"].amount)
    paid = sum(got)
    fees = c.balance(c.fee) - start["fee"] + c.balance(c.tip) - start["tip"]
    refunds = c.balance(baltok) - after_fund
    left = sum(c.held(x["address"]) for x in orders) + c.balance(pay.vault_pda(c.usdc))
    still = sum(1 for x in orders if c.data(x["address"]) is not None)
    marked = {"fund": sum(1 for x in orders if c.data(pay.used_pda(x["fund_sig"])) is not None)}
    # PayOrder's marker: counted when this build's PayOrder takes one (the instruction the harness builds names it)
    # (the harness adds the marker's account when it sends, so the instruction is read as it was sent)
    if any(a.pubkey == pay.used_pda(orders[0]["pay_sig"]) for a in c.marked(orders[0]["pay_ix"]).accounts):
        marked["pay"] = sum(1 for x in orders if c.data(pay.used_pda(x["pay_sig"])) is not None)
    replay_rows = [r for r in meter.rows if r.phase == "replay"]
    inv = {"orders": n, "open_at_once": open_at_once, "paid_exactly_once": once, "paid_twice_or_short": n - once, "funded": funded, "paid": paid,
           "fees": fees, "refunds": refunds, "left_in_order_accounts_and_vault": left, "orders_still_open": still,
           "markers": marked, "markers_expected": n, "sent_twice": sent_twice, "sent_after_close": sent_late,
           "replays_refused": sum(1 for r in replay_rows if not r.ok), "replays_accepted": sum(1 for r in replay_rows if r.ok)}
    inv["ok"] = bool(once == n and paid + fees + refunds == funded and left == 0 and still == 0 and inv["replays_accepted"] == 0
                     and all(v == n for v in marked.values()))
    good = [r for r in meter.rows if r.ok and r.phase in ("fund", "pay")]
    stages = {s: stage_stats([r for r in good if r.stage == s], n, roles) for s in STAGES}
    stages["verify"]["tokens_per_order"] = 2
    return {"cluster": "local simulator (LiteSVM)", "date": datetime.date.today().isoformat(), "seed": seed, "fixtures": fixtures(),
            "simulator_seconds": round(time.monotonic() - began, 1), "invariants": inv, "stages": stages,
            "derived": derive(stages), "derived_before_simd_0286": derive(stages, block_cu=LIMITS["block_cu_before"])}


# == the devnet tier ===================================================================================================
class Rpc:
    """A cluster's JSON-RPC endpoint. A test hands `run_devnet` anything else with a `call`."""
    def __init__(self, url: str):
        self.url = url

    def call(self, method: str, params: list):
        """A public endpoint's rate limit (HTTP 429) that outlasts chain.call's own backoff is waited out here too: K
        senders polling one endpoint meet it, and it says nothing about the transactions, so it must not end the run."""
        for wait in (5, 10, 20, 30, None):
            try:
                return chain.call(self.url, method, params, timeout=30.0)
            except urllib.error.HTTPError as e:
                if e.code != 429 or wait is None:
                    raise
                time.sleep(wait)


@dataclass
class Sent:
    ok: bool
    signature: str | None
    submitted: float            # when it was first handed to the cluster
    retries: int = 0
    why: str | None = None
    finalized: float | None = None
    blockhash: str | None = None


@dataclass
class Sender:
    """Signs, submits and waits. A transaction that does not land before `within` seconds is signed over a new
    blockhash and sent again (a retry), `tries` times in all; one the cluster refuses is a failure, with its words."""
    rpc: object
    payer: Keypair
    tries: int = 4
    within: float = 60.0
    poll: float = 1.0
    clock: object = time.monotonic
    sleep: object = time.sleep
    lock: threading.Lock = field(default_factory=threading.Lock)

    def statuses(self, signatures: list[str]) -> list[dict | None]:
        return self.rpc.call("getSignatureStatuses", [signatures, {"searchTransactionHistory": True}])["value"]

    def blockhash(self, after: str | None) -> str:
        """A recent blockhash that is not `after`. The two steps that check a 2048-bit signature are the same
        instruction: signed over one blockhash they would be one transaction, and the second would never run."""
        end = self.clock() + self.within
        while True:
            got = self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
            if got != after or self.clock() >= end:
                return got
            self.sleep(self.poll / 2)

    def send(self, ixs, signers=(), after: str | None = None) -> Sent:
        """Lands one transaction (`confirmed`), so that the next one of the same token or order can build on it.
        `after`: the blockhash the transaction before it was signed over."""
        first, why, sig = self.clock(), None, None
        for attempt in range(self.tries):
            recent = self.blockhash(after)
            raw = base64.b64encode(bytes(chain.sign(ixs, self.payer, list(signers), Hash.from_string(recent)))).decode()
            try:
                sig = self.rpc.call("sendTransaction", [raw, {"encoding": "base64", "preflightCommitment": "confirmed", "maxRetries": 3}])
            except Exception as e:  # noqa: BLE001 - a refusal is a result here: it is counted and reported
                why = str(e)[:300]
                if "blockhash" in why.lower().replace(" ", "") and "notfound" in why.lower().replace(" ", ""):
                    continue                    # the endpoint has not seen that block yet, or it has aged out: sign again
                return Sent(False, sig, first, attempt, why, blockhash=recent)
            end = self.clock() + self.within
            while self.clock() < end:
                st = self.statuses([sig])[0]
                if st and st.get("err"):
                    return Sent(False, sig, first, attempt, f"failed on chain: {st['err']}", blockhash=recent)
                if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                    return Sent(True, sig, first, attempt, blockhash=recent)
                self.sleep(self.poll)
            why = f"not confirmed within {self.within:.0f}s"
        return Sent(False, sig, first, self.tries - 1, why)

    def finalize(self, sent: list[Sent]) -> None:
        """Waits until every landed transaction is `finalized` and notes when it was first seen so (to within `poll`).
        One that the cluster dropped after confirming it becomes a failure."""
        end = self.clock() + 2 * self.within
        waiting = [s for s in sent if s.ok]
        while waiting and self.clock() < end:
            for s, st in zip(waiting, self.statuses([s.signature for s in waiting])):
                if st and st.get("confirmationStatus") == "finalized":
                    s.finalized = self.clock()
            waiting = [s for s in waiting if s.finalized is None]
            if waiting:
                self.sleep(self.poll)
        for s in waiting:
            s.ok, s.why = False, "confirmed but not finalized in time"


def unit(sender: Sender, groups) -> list[Sent]:
    """One token or one order: its transactions in turn, each built on the one before; then all of them finalized."""
    sent: list[Sent] = []
    for ixs in groups:
        sent.append(sender.send(ixs, after=sent[-1].blockhash if sent else None))
        if not sent[-1].ok:
            break
    sender.finalize(sent)
    return sent


def stage(sender: Sender, units: list, senders: int) -> tuple[dict, list[bool]]:
    """Runs the units `senders` at a time. Returns the stage's record and, per unit, whether all of it finalized."""
    with ThreadPoolExecutor(max_workers=max(1, senders)) as pool:
        done = list(pool.map(lambda groups: unit(sender, groups), units))
    txs = [s for d in done for s in d]
    lat = [round(s.finalized - s.submitted, 2) for s in txs if s.ok]
    good = [len(d) == len(u) and all(s.ok for s in d) for d, u in zip(done, units)]
    whole = [round(max(s.finalized for s in d) - d[0].submitted, 2) for d, g in zip(done, good) if g]
    spread = lambda v: {"p50": pct(v, 50), "p95": pct(v, 95), "p99": pct(v, 99), "max": max(v, default=None)}  # noqa: E731
    return {"units": len(units), "units_finalized": sum(good), "transactions": len(txs), "failures": sum(1 for s in txs if not s.ok),
            "retries": sum(s.retries for s in txs), "tx_submit_to_finalized_s": spread(lat), "unit_submit_to_finalized_s": spread(whole),
            "first_failures": [s.why for s in txs if not s.ok][:5]}, good


NOT_EXERCISED = {
    "pay": "knos_pay takes a token GitHub did not sign only in PayOrder on a PRIVATE order funded from a Balance, under a key the Balance's own wallet "
           "registered; that order is funded by FundOrderBalance, which takes GitHub's tokens only, one per order. A test issuer cannot fund and pay "
           "N orders, so PayOrder was not sent on the cluster; its compute units are measured in the local simulator.",
    "fund from a Balance": "FundOrderBalance and the faucet take GitHub's tokens only. The orders were funded by a wallet (FundOrderWallet), in a "
                           "mint made for the run.",
    "meter": "knos_meter takes GitHub's tokens only.",
}
ISSUER_URL = "https://issuer.invalid/knos-load"    # names nothing real: a private key's URL is the registrant's own word
WF_REPO, WF_SHA = "drexthealpha/Knos", "c" * 40    # what the orders pin; nothing in this run is ever judged by it
# what the orders are funded with: terms in the canonical form knos.terms.parse reads, as a judge must read them to pay
TERMS = terms.canonical({"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"], "mode": "merge", "paths": [],
                         "reserve": 0, "v": 1})


def issuer_token(key, url: str, now: int, i: int, run: str) -> str:
    """A token as a CI issuer would sign it: RS256, the issuer's URL, five minutes of life, an audience of its own."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    claims = {"iss": url, "sub": f"load:{run}:{i}", "aud": f"knos-load:{run}:{i}", "iat": now, "nbf": now - 60, "exp": now + 300, "jti": f"{run}-{i}"}
    data = (b64(json.dumps({"typ": "JWT", "alg": "RS256", "kid": "load"}, separators=(",", ":")).encode()) + "."
            + b64(json.dumps(claims, separators=(",", ":")).encode())).encode()
    return data.decode() + "." + b64(key.sign(data, padding.PKCS1v15(), hashes.SHA256()))


def mint_ixs(payer: Pubkey, mint: Pubkey, rent: int, amount: int) -> list[Instruction]:
    """A plain SPL Token mint of six decimals, the wallet's token account of it, and `amount` minted there."""
    token = pay.ata(payer, mint)
    return [create_account(CreateAccountParams(from_pubkey=payer, to_pubkey=mint, lamports=rent, space=82, owner=pay.TOKEN)),
            Instruction(pay.TOKEN, bytes([20, 6]) + bytes(payer) + b"\x00", [AccountMeta(mint, False, True)]),
            pay.create_ata_ix(payer, payer, mint),
            Instruction(pay.TOKEN, b"\x07" + amount.to_bytes(8, "little"), [AccountMeta(mint, False, True), AccountMeta(token, False, True),
                                                                           AccountMeta(payer, True, False)])]


def accounts(rpc, addresses) -> list[bytes | None]:
    out: list[bytes | None] = []
    for i in range(0, len(addresses), 100):
        got = rpc.call("getMultipleAccounts", [[str(a) for a in addresses[i:i + 100]], {"encoding": "base64", "commitment": "finalized"}])["value"]
        out += [base64.b64decode(a["data"][0]) if a else None for a in got]
    return out


def chain_time(rpc) -> int:
    return int(rpc.call("getBlockTime", [rpc.call("getSlot", [{"commitment": "confirmed"}])]))


def token_balance(rpc, account: Pubkey) -> int:
    d = accounts(rpc, [account])[0]
    return int.from_bytes(d[64:72], "little") if d and len(d) >= 72 else 0


def run_devnet(rpc, wallet: Keypair, issuer_key, n: int, senders: int = 8, url: str = ISSUER_URL, amount: int = 5_000_000, work_s: int = 60,
               refund: bool = True, sender: Sender | None = None, name: str = "devnet") -> dict:
    s = sender or Sender(rpc, wallet)
    me, modulus = wallet.pubkey(), issuer_key.public_key().public_numbers().n
    run = hashlib.sha256(bytes(Keypair().pubkey())).hexdigest()[:10]      # tokens and orders of two runs never collide
    key = oidc.key_pda(url, modulus, registrant=me)
    out = {"cluster": name, "date": datetime.date.today().isoformat(), "orders": n, "senders": senders, "run": run, "wallet": str(me),
           "issuer": url, "key_account": str(key), "programs": {"knos_oidc": str(oidc.OIDC_ID), "knos_pay": str(pay.PAY_ID)},
           "stages": {}, "not_exercised": NOT_EXERCISED}

    # -- setup: the issuer's key as the wallet's PRIVATE key, and a mint of the wallet's own ---------------------------
    mint = Keypair()
    each = amount + 2 * max(fees.NEW.order(amount), fees.OLD.order(amount)) + 1_000_000        # room for the fee whichever rule the live build charges (knos.fees)
    rent = int(rpc.call("getMinimumBalanceForRentExemption", [82]))
    setup = [s.send([oidc.register_private_key_ix(me, url, modulus)]), s.send([oidc.key_params_ix(me, url, modulus, registrant=me)]),
             s.send(mint_ixs(me, mint.pubkey(), rent, n * each), [mint])]
    s.finalize(setup)
    out["mint"] = str(mint.pubkey())
    if not all(x.ok for x in setup):
        out["stopped"] = "setup failed: " + "; ".join(x.why or "ok" for x in setup)
        return out
    wallet_token = pay.ata(me, mint.pubkey())
    minted = token_balance(rpc, wallet_token)

    # -- verify: n tokens, each written and verified on chain ----------------------------------------------------------
    now = chain_time(rpc)
    jwts = [issuer_token(issuer_key, url, now, i, run) for i in range(n)]
    tids = [oidc.token_id(j) for j in jwts]
    plan = oidc.step_plan(modulus.bit_length())
    units = [[[ix] for ix in oidc.write_ixs(me, tid, jwt)] + [[oidc.step_ix(me, tid, key, sq)] for sq in plan] for jwt, tid in zip(jwts, tids)]
    out["stages"]["verify"], _ = stage(s, units, senders)
    seen = [oidc.token_issuer(d) for d in accounts(rpc, [oidc.token_pda(me, t) for t in tids])]
    out["stages"]["verify"]["verified_on_chain"] = sum(1 for t in seen if t is not None and t[1] == me and t[0] == oidc.issuer_hash(url))

    # -- fund: n orders on n repositories, by the wallet, with the shortest work time ---------------------------------
    base = 2_000_000_000 + int(run[:6], 16)
    places = [(base + i, 1 + i) for i in range(n)]
    orders = [pay.order_pda(pay.scope_of(repo, num), me) for repo, num in places]
    units = [[[pay.fund_order_wallet_ix(me, wallet_token, mint.pubkey(), repo, num, amount, WF_REPO, WF_SHA, TERMS, work_s=work_s)]] for repo, num in places]
    out["stages"]["fund"], funded = stage(s, units, senders)
    read = [pay.read_order(d) for d in accounts(rpc, orders)]
    out["stages"]["fund"]["open_on_chain"] = sum(1 for o in read if o is not None and o.state == "open" and o.amount == amount)
    held = minted - token_balance(rpc, wallet_token)
    out["checks"] = {"minted": minted, "held_by_orders": held, "held_equals_funded": held == sum(o.amount + o.fee for o in read if o is not None)}

    # -- refund: after the deadline every order gives back what it holds, and every token account is closed -----------
    if refund:
        last = max((o.deadline for o in read if o is not None), default=0)
        while chain_time(rpc) <= last:
            s.sleep(5.0)
        units = [[[pay.refund_order_ix(me, a, o, wallet_token)]] for a, o in zip(orders, read) if o is not None]
        out["stages"]["refund"], _ = stage(s, units, senders)
        closes = [[[oidc.close_ix(me, t)]] for t, v in zip(tids, seen) if v is not None]
        out["stages"]["close"], _ = stage(s, closes, senders)
        back = token_balance(rpc, wallet_token)
        out["checks"].update(orders_left=sum(1 for d in accounts(rpc, orders) if d is not None), returned=back, nothing_lost=back == minted)
    out["ok"] = bool(out["stages"]["verify"]["verified_on_chain"] == n and out["stages"]["fund"]["open_on_chain"] == n
                     and out["checks"]["held_equals_funded"] and (not refund or (out["checks"]["nothing_lost"] and out["checks"]["orders_left"] == 0)))
    return out


# == throughput, measured ==============================================================================================
PHASES = {"apart": "no account written by two relays", "shared": "every transaction also writes one token account, as every release writes the fee account"}
REDUCES = [
    ("Several fee payers", "exists: `KNOS_RELAY_KEYS` (docs/RELAY.md). Each owner's tokens always pay from the same one of the keys, so the relays stop "
                           "sharing the one account that pays the fees: the per-relayer ceiling of section 3 is per key."),
    ("One release for many small outcomes", "exists: `knos net` (docs/NETTING.md) settles outcomes under 20 USD as one release per payee per period, so "
                                            "the fee account is written once per payee per period and not once per outcome."),
    ("One transaction for many evaluations", "exists: the meter's RecordBatch counts a period's evaluations in one transaction and moves no money, so it "
                                             "does not write the fee account at all."),
    ("A fee account per mint", "exists by construction: the fee account is the fee owner's token account OF THE ORDER'S MINT, so orders in two mints do not "
                               "share it. Every order Knos has funded is in one mint, so this has not been used."),
    ("Several fee accounts for one mint", "does NOT exist and needs a program change: the release instruction takes the one account. Not in this release."),
]


def relay_keys(wallet: Keypair, n: int) -> list[Keypair]:
    """The relays' fee payers, derived from the wallet's own key: the same every run, so SOL a run that died left in
    them is swept by the next (`measure --relays N --orders 0`). Nothing is stored and none is printed."""
    return [Keypair.from_seed(hashlib.sha256(bytes(wallet)[:32] + b"knos-load-relay" + i.to_bytes(2, "little")).digest()) for i in range(n)]


def _token_transfer(source: Pubkey, dest: Pubkey, owner: Pubkey, amount: int) -> Instruction:
    return Instruction(pay.TOKEN, b"\x03" + amount.to_bytes(8, "little"), [AccountMeta(source, False, True), AccountMeta(dest, False, True), AccountMeta(owner, True, False)])


def _slots(rpc, signatures: list[str]) -> list[int]:
    out: list[int] = []
    for i in range(0, len(signatures), 200):
        got = rpc.call("getSignatureStatuses", [signatures[i:i + 200], {"searchTransactionHistory": True}])["value"]
        out += [int(st["slot"]) for st in got if st and st.get("slot") is not None]
    return out


def measure(rpc, wallet: Keypair, relays: int, orders: int, amount: int = 5_000_000, work_s: int = 60, sol_per_order: int = 12_000_000,
            sender=None, name: str = "devnet", say=lambda _line: None) -> dict:
    """See the module's words on `measure`. `sender(payer)` makes a Sender (the tests give one with a fake clock).
    `sol_per_order`: lamports a relay is lent per order it funds (rent it gets back at the refund, and fees)."""
    from solders.system_program import TransferParams, transfer
    make = sender or (lambda payer: Sender(rpc, payer))
    s, me, keys = make(wallet), wallet.pubkey(), relay_keys(wallet, relays)
    share = [orders // relays + (1 if r < orders % relays else 0) for r in range(relays)]
    run = hashlib.sha256(bytes(Keypair().pubkey())).hexdigest()[:10]
    out: dict = {"cluster": name, "date": datetime.date.today().isoformat(), "relays": relays, "orders": orders, "run": run, "wallet": str(me),
                 "fee_payers": [str(k.pubkey()) for k in keys], "program": str(pay.PAY_ID), "phases": {}, "what": PHASES}
    balance = lambda who: int(rpc.call("getBalance", [str(who), {"commitment": "confirmed"}])["value"])  # noqa: E731
    began = balance(me)

    def sweep() -> None:
        back = []
        for k in keys:
            have = balance(k.pubkey())
            if have > 5_000:
                back.append(make(k).send([transfer(TransferParams(from_pubkey=k.pubkey(), to_pubkey=me, lamports=have - 5_000))]))
        out["swept"] = sum(1 for x in back if x.ok)
        out["sol_spent"] = round((began - balance(me)) / 1e9, 6)

    if orders <= 0:
        sweep()
        out["ok"] = True
        return out
    # -- setup: a mint, the account every `shared` transaction writes, and each relay's SOL and tokens --------------------
    mint = Keypair()
    each = amount + 2 * max(fees.NEW.order(amount), fees.OLD.order(amount)) + 1_000_000
    rent = int(rpc.call("getMinimumBalanceForRentExemption", [82]))
    shared = pay.ata(me, mint.pubkey())
    setup = [s.send(mint_ixs(me, mint.pubkey(), rent, 2 * orders * each), [mint])]
    for k, m in zip(keys, share):
        if setup[-1].ok and m:
            setup.append(s.send([transfer(TransferParams(from_pubkey=me, to_pubkey=k.pubkey(), lamports=2 * m * sol_per_order + 10_000_000)),
                                 pay.create_ata_ix(me, k.pubkey(), mint.pubkey()),
                                 _token_transfer(shared, pay.ata(k.pubkey(), mint.pubkey()), me, 2 * m * each)]))
    out["mint"], out["shared_account"] = str(mint.pubkey()), str(shared)
    if not all(x.ok for x in setup):
        out["stopped"] = "setup failed: " + "; ".join(x.why or "ok" for x in setup)
        sweep()
        return out
    base = 2_100_000_000 + int(run[:5], 16)
    funded: list[tuple[Keypair, Pubkey]] = []
    try:
        for p, phase in enumerate(PHASES):
            def one(r: int, p=p, phase=phase) -> list[tuple[Sent, float, Pubkey]]:
                k, mine, done = keys[r], make(keys[r]), []
                token = pay.ata(k.pubkey(), mint.pubkey())
                for i in range(share[r]):
                    repo, num = base + p * 1_000_000 + r * 10_000 + i, 1 + i
                    ixs = [pay.fund_order_wallet_ix(k.pubkey(), token, mint.pubkey(), repo, num, amount, WF_REPO, WF_SHA, TERMS, work_s=work_s)]
                    if phase == "shared":
                        ixs.append(_token_transfer(token, shared, k.pubkey(), 1))
                    sent = mine.send(ixs)
                    done.append((sent, mine.clock(), pay.order_pda(pay.scope_of(repo, num), k.pubkey())))
                return done
            with ThreadPoolExecutor(max_workers=relays) as pool:
                per = list(pool.map(one, range(relays)))
            flat = [x for d in per for x in d]
            good = [(sent, at) for sent, at, _o in flat if sent.ok]
            funded += [(keys[r], o) for r, d in enumerate(per) for sent, _at, o in d if sent.ok]
            wall = max((at for _s, at in good), default=0.0) - min((sent.submitted for sent, _at in good), default=0.0)
            slots = _slots(rpc, [sent.signature for sent, _at in good])
            waits = [round(at - sent.submitted, 2) for sent, at in good]
            out["phases"][phase] = {
                "transactions": len(flat), "confirmed": len(good), "failures": len(flat) - len(good), "retries": sum(sent.retries for sent, _a, _o in flat),
                "seconds": round(wall, 2), "confirmed_per_s": round(len(good) / wall, 2) if wall > 0 else None,
                "confirm_s": {"p50": pct(waits, 50), "p95": pct(waits, 95), "max": max(waits, default=None)},
                "slots": len(set(slots)), "most_in_one_slot": max((slots.count(x) for x in set(slots)), default=0),
                "first_failures": [sent.why for sent, _a, _o in flat if not sent.ok][:5]}
            say(f"{phase}: {len(good)} of {len(flat)} confirmed in {wall:.1f} s, {out['phases'][phase]['retries']} retries")
        a, b = out["phases"]["apart"], out["phases"]["shared"]
        out["contention"] = {
            "rate_shared_over_apart": round(b["confirmed_per_s"] / a["confirmed_per_s"], 2) if a["confirmed_per_s"] and b["confirmed_per_s"] else None,
            "retries_more": b["retries"] - a["retries"], "failures_more": b["failures"] - a["failures"],
            "most_in_one_slot": {"apart": a["most_in_one_slot"], "shared": b["most_in_one_slot"]}}
        # -- every order refunded after its deadline, by the relay that funded it ----------------------------------------
        read = [pay.read_order(d) for d in accounts(rpc, [o for _k, o in funded])]
        last = max((o.deadline for o in read if o is not None), default=0)
        while chain_time(rpc) <= last:
            s.sleep(5.0)

        def refund(item) -> bool:
            (k, address), o = item
            return o is None or make(k).send([pay.refund_order_ix(k.pubkey(), address, o, pay.ata(k.pubkey(), mint.pubkey()))]).ok
        with ThreadPoolExecutor(max_workers=relays) as pool:
            back = list(pool.map(refund, zip(funded, read)))
        out["refunded"] = sum(back)
        out["orders_left"] = sum(1 for d in accounts(rpc, [o for _k, o in funded]) if d is not None)
    finally:
        sweep()
    out["ok"] = bool(all(x["confirmed"] == orders for x in out["phases"].values()) and out.get("orders_left") == 0)
    return out


def render_measured(doc: dict) -> list[str]:
    """Measured on devnet, the derived bound, and what reduces shared writable state: three things kept apart."""
    runs = [m for m in doc.get("measured") or [] if m.get("cluster") == "devnet"]
    out = ["### Throughput with relays side by side: measured, and derived", "",
           "`python scripts/load.py measure --relays N --orders M --wallet <keypair> --write`, run by the operator at release. N relays, each with "
           "a fee payer of its own, each fund their share of M orders one after another (a key signs for one thing at a time), twice: `apart`, "
           "where no two relays write an account in common, and `shared`, where every transaction also writes one token account. That account "
           "stands for the fee account, which every release of a mint writes whoever relays it. A rate is confirmed transactions divided by the "
           "seconds from the first submission to the last confirmation. PayOrder is not sent (the table above says why): this measures funding "
           "with and without one shared writable account, not payments.", ""]
    if not runs:
        out += ["**Measured on devnet: nothing yet.** The command has run here against the local simulator only (`--simulate`, "
                "`tests/test_load_measure.py`), which proves the path and gives no rate: it has no leader, no block limit and no other traffic. "
                "Until the release run records one, this page holds no measured throughput.", ""]
    for m in runs:
        kind = MEASURED_KIND.get(m.get("kind", "fund"), m.get("kind", "fund"))
        if m.get("kind") == "pay" and "phases" not in m:            # scripts/load_pay.py's record: one row of payments
            out += paid_rows(m, kind)
            continue
        out += [f"#### Measured on devnet, {ids_of(m.get('programs') or m.get('program'))}, {m['date']}: {kind}; {m['relays']} relays, {m['orders']:,} orders each way"
                + ("" if m.get("ok") else " (did not complete cleanly)"), "",
                "| | Confirmed | Seconds | Confirmed a second | Retries | Failures | Confirm p50 s | p95 | p99 | worst | Slots used | Most in one slot |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for name, x in m["phases"].items():
            c = x["confirm_s"]
            p99 = c.get("p99", "none: fewer than 100 samples" if x["confirmed"] < 100 else "not kept")
            out.append(f"| {name}: {m['what'][name]} | {x['confirmed']:,} of {x['transactions']:,} | {x['seconds']} | {x['confirmed_per_s']} | {x['retries']} | "
                       f"{x['failures']} of {x['transactions']:,} | {c['p50']} | {c['p95']} | {p99} | {c.get('max', 'not kept')} | {x['slots']} | {x['most_in_one_slot']} |")
        c = m.get("contention") or {}
        out += ["", f"The contention seen: the shared account's rate was {c.get('rate_shared_over_apart')} of the rate apart, with {c.get('retries_more')} more "
                f"retries and {c.get('failures_more')} more failures. It cost {m.get('sol_spent')} SOL in fees and rent not recovered. Wallet `{m['wallet']}`, "
                f"mint `{m.get('mint')}`, shared account `{m.get('shared_account')}`." + (f" Stopped: {m['stopped']}." if m.get("stopped") else ""), ""]
    if not any(m.get("kind") == "pay" for m in runs):
        out += ["**Not measured: end-to-end PayOrder capacity.** Every rate above is of funding (FundOrderWallet) alone. No run has sent "
                "PayOrder, the transaction that writes the fee account of the mint, side by side on a cluster, so how many payments a second "
                "the whole path carries (token verification, then PayOrder, through the one fee account) has no measured figure, on the "
                "public program ids or on staging. The derived ceiling below is arithmetic. The command that will measure it: "
                "`python scripts/load.py measure --pay --relays 4 --tokens <pay tokens GitHub signed> --wallet <keypair> --write`. A run of it is recorded here "
                "under its own heading, with its ids and date.", ""]
    if doc.get("local"):
        d = doc["local"]["derived"]
        out += ["**Derived bound (not measured).** Section 3's arithmetic from the simulator's compute units and Solana's published limits: "
                f"{d['one_relayer_orders_per_second']} orders a second per fee payer (verification included), {d['fee_account_orders_per_second']} "
                f"payments a second through the one fee account of a mint, {d['one_balance_orders_per_second']} fundings a second from one Balance. "
                "These are ceilings in an otherwise empty block. A measured rate above is of devnet on the day, with its own traffic, through one "
                "public endpoint, and each relay waits for a confirmation before it sends again: the two are different quantities, and neither "
                "is used in place of the other.", ""]
    out += ["**What reduces shared writable state without a program change:**", "", "| Way | State |", "| --- | --- |"]
    out += [f"| {way} | {state} |" for way, state in REDUCES]
    return out + [""]


# == the documents =====================================================================================================
ABOUT = ("Load measurements; scripts/load.py writes this file and renders docs/LOAD.md from it. local: N orders through the committed test builds in "
         "LiteSVM (compute units exact, cluster time derived). runs: what an operator measured on a cluster with a test issuer, newest last.")


def usd(micro: int) -> str:
    return f"{micro / 1_000_000:,.2f}"


PUBLIC_IDS = ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json"


def paid_rows(m: dict, kind: str) -> list[str]:
    """One end-to-end PayOrder run of scripts/load_pay.py on a cluster: every payment attempted, what became of each,
    and the seconds of the ones paid, p50, p95 and p99 apart (no p99 below 100 payments)."""
    progs = {k: v for k, v in (m.get("programs") or {}).items() if k != "ids"}
    c = m.get("payment_s") or {}
    p99 = c.get("p99") if m.get("paid", 0) >= 100 else "none: fewer than 100 payments"
    out = [f"#### Measured on devnet, {ids_of(progs)}, {m['date']}: {kind}; {m['relays']} relays, {m.get('attempted', 0):,} payments attempted"
           + ("" if m.get("ok") else " (did not complete cleanly)"), "",
           "| Attempted | Paid | Carried first by another relay | Refused | Never completed | Seconds | Paid a second | Payment p50 s | p95 | p99 | worst |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
           f"| {m.get('attempted', 0):,} | {m.get('paid', 0):,} of {m.get('attempted', 0):,} | {m.get('already', 0)} | {m.get('refused', 0)} | "
           f"{m.get('never_completed', 0)} | {m.get('seconds')} | {m.get('paid_per_s')} | {c.get('p50')} | {c.get('p95')} | {p99} | {c.get('max')} |", ""]
    said = (f"A payment's seconds run from its first submission to the relay's answer: the token written, GitHub's signature verified, then "
            f"PayOrder. Each relay paid from a fee payer of its own ({', '.join(f'`{k}`' for k in m.get('fee_payers') or [])}), lent its SOL by "
            f"wallet `{m.get('wallet')}` and swept back.")
    if m.get("first_refusals"):
        said += " The first refusals: " + "; ".join(m["first_refusals"]) + "."
    if m.get("stopped"):
        said += f" Stopped: {m['stopped']}."
    return out + [said, ""]


def ids_of(programs) -> str:
    """Which program ids a cluster run used, in the words every heading prints: "public program ids" when each one is
    a public id (src/knos/settle/v2/program_ids.json), "STAGING program ids (not the public ones)" when none is,
    "program ids not recorded" when the run did not keep them. `programs`: {name: id} or one id."""
    got = [programs] if isinstance(programs, str) else list((programs or {}).values())
    if not got:
        return "program ids not recorded"
    public = {v for v in json.loads(PUBLIC_IDS.read_text(encoding="utf-8")).values() if isinstance(v, str)}
    if all(x in public for x in got):
        return "public program ids"
    if not any(x in public for x in got):
        return "STAGING program ids (not the public ones)"
    return "public and STAGING program ids mixed"


def _when(source: str) -> str:
    """The date a source sentence names (2026-10-06, or 6 October 2026), else "date not recorded"."""
    m = re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2} (?:January|February|March|April|May|June|July|August|September|October|November|December) \d{4}", source or "")
    return m.group(0) if m else "date not recorded"


def render(doc: dict) -> str:
    L, loc = doc["limits"], doc.get("local")
    out = ["# Load: many orders open at once", "",
           "<!-- written by scripts/load.py from docs/load.json; change the numbers there by running it, not here -->", "",
           "The claim this page tests: 1,000 funded orders open at once, each settled in under a minute of submission, with no order paid twice "
           "and none lost. The second half (paid once, none lost) is measured. The first half (a minute) is derived from what was measured, and "
           "holds or does not hold depending on how many relayers carry the tokens; the table below says which.", "",
           "Everything in the first three sections was **measured in the local simulator** (LiteSVM, the same virtual machine a validator runs, "
           "with the test builds in `tests/fixtures`). **Compute units are exact**: a cluster charges the same program the same units. "
           "**Wall-clock time on a cluster is derived** from those units and Solana's published limits; it was not observed.", ""]
    if loc:
        i, st, d = loc["invariants"], loc["stages"], loc["derived"]
        pm = i["markers"].get("pay")
        out += [f"## 1. Paid once, none lost ({i['orders']:,} orders)", "",
                f"`python scripts/load.py --local {i['orders']}` on {loc['date']} (seed {loc['seed']}). {i['orders']:,} orders on {i['orders']:,} "
                "different repositories and issues were funded from one Balance by tokens the harness signs with the test key, and all were open "
                "before the first was paid. They were then paid in a shuffled order, four in five to one payee and one in five to two. Every "
                "10th fund token and every 10th pay token was sent a second time at once; every 50th order's fund token and pay token were sent "
                "again after the order had closed.", "",
                "| Check | Result |", "| --- | --- |",
                f"| Orders open at the same time | {i['open_at_once']:,} of {i['orders']:,} |",
                f"| Orders whose payees hold exactly the order's amount (paid once) | {i['paid_exactly_once']:,} of {i['orders']:,} |",
                f"| Orders paid twice or short | {i['paid_twice_or_short']} |",
                f"| Left the Balance (funded), test USDC | {usd(i['funded'])} |",
                f"| Reached payees, test USDC | {usd(i['paid'])} |",
                f"| Fees, the relayer's tips included | {usd(i['fees'])} |",
                f"| Came back to the Balance (refunds) | {usd(i['refunds'])} |",
                f"| paid + fees + refunds == funded | {'yes' if i['paid'] + i['fees'] + i['refunds'] == i['funded'] else 'NO'} |",
                f"| Left in any order's account or the shared vault | {usd(i['left_in_order_accounts_and_vault'])} |",
                f"| Order accounts still open | {i['orders_still_open']} |",
                f"| Single-use markers of fund tokens present | {i['markers']['fund']:,} of {i['markers_expected']:,} |",
                "| Single-use markers of pay tokens present | "
                + (f"{pm:,} of {i['markers_expected']:,} |" if pm is not None else "not counted: the PayOrder of the measured build takes no marker |"),
                f"| Tokens sent twice at once, accepted the second time | {i['sent_twice']} sent, 0 accepted |"
                if i["replays_accepted"] == 0 else f"| Replays accepted | {i['replays_accepted']} |",
                f"| Tokens sent again after their order closed, accepted | {i['sent_after_close']} sent, {i['replays_accepted']} accepted |", "",
                "The measured builds: " + ", ".join(f"`{f}` sha256 `{h[:16]}`" for f, h in loc["fixtures"].items()) + ".", "",
                "## 2. What one order costs", "",
                "| Stage | Transactions per order | Compute units per order p50 | p95 | max | Largest transaction (CU) | Bytes per order p50 | "
                "Largest transaction (bytes) |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        names = {"verify": "Token verification (knos_oidc), two tokens", "fund": "Fund (FundOrderBalance)", "pay": "Pay (PayOrder)"}
        for s in STAGES:
            x = st[s]
            out.append(f"| {names[s]} | {x['tx_per_order']['p50']} | {x['cu_per_order']['p50']:,} | {x['cu_per_order']['p95']:,} | "
                       f"{x['cu_per_order']['max']:,} | {x['cu_per_tx_max']:,} | {x['bytes_per_order']['p50']:,} | {x['bytes_per_tx_max']:,} |")
        out += ["", "What each number is:", "",
                "- **Stage.** An order needs two tokens, one that funds it and one that pays it. *Token verification* is every knos_oidc "
                "transaction for both: the token written into its account in pieces, then the RSA signature checked in steps. *Fund* and *Pay* "
                "are the one knos_pay transaction each token is then handed to.",
                "- **Transactions per order.** Successful transactions of that stage for one order. Refused duplicates are not counted here.",
                "- **Compute units per order.** The sum, over those transactions, of what the runtime reports each consumed (the whole "
                "transaction, the programs it calls included). p50, p95 and max are over the orders (nearest rank).",
                "- **Largest transaction.** The most one transaction of the stage consumed; a transaction may use "
                f"{L['tx_cu']:,}. And the most one weighed, signatures included; a cluster takes {L['tx_bytes']:,} bytes.",
                "- **Bytes per order.** The sum of the signed transactions' sizes.", "",
                "## 3. What that allows on a cluster (derived)", "",
                f"Solana's limits: a block holds {L['block_cu'] // 10 ** 6}M compute units ({L['block_cu_before'] // 10 ** 6}M until SIMD-0286; "
                f"mainnet has had the larger blocks since 29 July 2026, devnet since earlier), the transactions that write any one account may "
                f"use {L['account_cu'] // 10 ** 6}M of a block, and a block is produced every {int(L['slot_s'] * 1000)} ms. Sources: "
                + ", ".join(f"[{t}]({u})" for t, u in doc["sources"].items()) + ". The two sources disagree on one figure: Solana's page says the "
                "per-account limit stays at 12M, while the development branch of the Agave validator carries 24,000,000 for that constant (read "
                "on 4 October 2026). This page uses 12M, the published figure for the live clusters; with 24M the per-relayer, per-Balance and "
                "fee-account rates below double.", "",
                f"One order costs {d['cu_per_order']:,} compute units in all (the mean of the measured orders). The accounts that every "
                "transaction of a stage writes, and so the ones that cap it:", ""]
        for s in STAGES:
            out.append(f"- **{names[s]}**: " + "; ".join(st[s]["written_by_every_tx"]) + ".")
        out += ["", "So there are three points of contention, and the shared vault is not one of them: each order's money is in its own token "
                "account, which only that order's transactions write.", "",
                f"1. **A relayer's own account.** Everything a relayer sends writes the account that pays its fees, so one relayer fits "
                f"{L['account_cu'] // 10 ** 6}M units in a block: **{d['one_relayer_orders_per_second']} orders a second**, verification included. "
                "Verification is nearly all of it, and it is the only stage more relayers speed up.",
                f"2. **The fee account.** Every PayOrder of a mint writes the one fee account, whoever relays it: at most "
                f"**{d['fee_account_orders_per_second']} payments a second** in that mint, however many relayers there are.",
                f"3. **A Balance.** Every order funded from one Balance writes it: at most {d['one_balance_orders_per_second']} fundings a second "
                "per Balance. Orders funded from different Balances, or by wallets, do not share it.", "",
                f"Time for {d['orders']:,} orders submitted at once, all from one Balance, if the block held nothing else and was packed perfectly:", "",
                f"| Relayers | Blocks ({L['block_cu'] // 10 ** 6}M) | Seconds | Orders a second | Bound by | All settled within a minute | "
                f"Seconds with {L['block_cu_before'] // 10 ** 6}M blocks |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for r, x in d["relayers"].items():
            out.append(f"| {r} | {x['blocks']} | {x['seconds']} | {x['orders_per_second']} | {x['bound_by']} | {'yes' if x['under_a_minute'] else 'no'} | "
                       f"{loc['derived_before_simd_0286']['relayers'][r]['seconds']} |")
        out += ["", "How it is derived: blocks = the largest of (all compute / the block limit), (all compute / relayers x 12M), (fund compute / "
                "12M) and (pay compute / 12M), rounded up; seconds = blocks x 0.4. It is a floor on the time, not a forecast: it counts only the "
                "compute the transactions consumed (a cluster also charges signatures, write locks and data against the same limits), it assumes "
                "the relayers split the tokens evenly and that no other transaction is in the block, and it ignores that the transactions of one "
                "token must land one after another. With one relayer the claim of a minute does **not** hold for 1,000 orders arriving together; "
                "the table shows from how many relayers it does." if not d["relayers"]["1"]["under_a_minute"] else
                "How it is derived: blocks = the largest of (all compute / the block limit), (all compute / relayers x 12M), (fund compute / 12M) "
                "and (pay compute / 12M), rounded up; seconds = blocks x 0.4. It is a floor on the time, not a forecast: it counts only the compute "
                "the transactions consumed, assumes an otherwise empty block and an even split between relayers.", ""]
    out += ["## 4. On a cluster (devnet)", "",
            "`python scripts/load.py --devnet N --issuer-key issuer.pem --wallet <keypair> --write`, run by the operator at release. GitHub will "
            "not sign a thousand tokens on demand, so a test issuer signs them, and its key is registered as a private key of the operator's "
            "wallet (knos_oidc's RegisterPrivateKey). That decides what a cluster run can and cannot exercise:", "",
            "| Stage | On the cluster | Why |", "| --- | --- | --- |",
            "| Token verification | exercised | knos_oidc verifies any RS256 issuer's tokens under a registered key |",
            "| Fund | exercised, from a wallet | FundOrderWallet takes no token |",
            "| Refund and close | exercised | every order is refunded after its deadline and every token account closed, so the run leaves nothing behind |",
            f"| Pay | **not exercised** | {NOT_EXERCISED['pay']} |",
            f"| Fund from a Balance, the faucet | **not exercised** | {NOT_EXERCISED['fund from a Balance']} |",
            f"| Meter | **not exercised** | {NOT_EXERCISED['meter']} |", "",
            "Latency is seconds from a transaction's first submission until the script first saw it `finalized` (it asks once a second), per "
            "transaction and per unit (a token: all its transactions; an order: its one). A retry is a transaction signed again because it did "
            "not land in time; a failure is one the cluster refused or lost.", ""]
    runs = doc.get("runs") or []
    if not runs:
        out += ["**No cluster run is recorded yet.** The path is unit-tested against a simulated RPC (`tests/test_load.py`); it has not been "
                "run on devnet.", ""]
    for r in runs:
        out += [f"### {r['cluster']}, {ids_of(r.get('programs'))}, {r['date']}: {r['orders']:,} orders, {r['senders']} senders"
                + ("" if r.get("ok") else " (did not complete cleanly)"), "",
                *([f"These {r['orders']:,} orders ran on the staging deployment, not on the public program ids: knos_oidc `{r['programs'].get('knos_oidc')}`, "
                   f"knos_pay `{r['programs'].get('knos_pay')}`. Every figure in this table is staging's; on the public program ids only the funding rate below was measured.", ""]
                  if ids_of(r.get("programs")).startswith("STAGING") else []),
                "| Stage | Units finalized | Transactions | Failures | Retries | Transaction p50 s | p95 | p99 | worst | Unit p50 s | p95 | p99 | worst |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for s, x in r["stages"].items():
            t, u = x["tx_submit_to_finalized_s"], x["unit_submit_to_finalized_s"]
            out.append(f"| {s} | {x['units_finalized']:,} of {x['units']:,} | {x['transactions']:,} | {x['failures']} of {x['transactions']:,} | {x['retries']} | "
                       f"{t['p50']} | {t['p95']} | {t['p99']} | {t.get('max', 'not kept')} | {u['p50']} | {u['p95']} | {u['p99']} | {u.get('max', 'not kept')} |")
        out += ["", f"Wallet `{r['wallet']}`, key account `{r['key_account']}`, mint `{r.get('mint')}`." + (f" Stopped: {r['stopped']}." if r.get("stopped") else ""), ""]
    out += render_measured(doc)
    if doc.get("workflow"):
        out += render_workflow(doc["workflow"], runs)
    if doc.get("relay"):
        out += render_relay(doc["relay"])
    return "\n".join(out).rstrip() + "\n"


def render_relay(rel: dict) -> list[str]:
    """Section 6, from docs/load.json's `relay` section: the stages of a payment as the public relay's log recorded
    them (`stages`: scripts/latency_stages.py's `six`, stored by `--stages`), and the local drill of the relay's queue
    (`queue`: scripts/queue_drill.py --write)."""
    out = ["## 6. The relay: where a payment's seconds go, and its queue", ""]
    st, q, sw = rel.get("stages"), rel.get("queue"), rel.get("sweep")
    if st:
        if str(ROOT / "scripts") not in sys.path:
            sys.path.append(str(ROOT / "scripts"))       # (a test loads this file by its path: its folder is then not on the path)
        import latency_stages
        n = [row["n"] for row in st["six"]]
        out += ["### The stages of a payment (recorded on devnet)", "",
                f"From {st['source']}. Every payment in it was made by the public program ids (the relay log's payments, read from their "
                f"escrows' history). Each stage is timed only for the payments whose log line recorded it, so each row has its own n; "
                f"a stage no line recorded says \"{latency_stages.NOT_RECORDED}\", and no figure here is derived from another row.", "",
                *latency_stages.table(st["six"], st["whole"]), "",
                f"Read it with its n. The whole wait is {st['whole']['n']} payments; the stage rows are {max(n)} of them, because the log lines of the other "
                f"{st['whole']['n'] - max(n)} carry no stage fields: for those payments every stage is "
                f"{latency_stages.NOT_RECORDED}, and their time is in the first row only. With {max(n)} samples the 95th percentile by nearest "
                "rank is the slowest of them, so a p95 in a stage row is one payment, not a band. `python scripts/latency_stages.py --md` prints "
                "this table from the live log.", ""]
        dec = rel.get("decision")
        most = max(n)
        out += ["### The five clocks", "",
                "\"How fast\" is five clocks, and they are not added up here. Each row has its own sample and says where it was measured; "
                "percentiles of different samples do not add. A target is a target, not a measurement.", "",
                *latency_stages.clock_table(latency_stages.clocks(st["six"], dec, st["whole"])), "",
                f"What was measured on devnet: {st['whole']['n']} payments have a whole wait (first table). Only {most} of those {st['whole']['n']} carry stage "
                f"times in their log line, so every devnet row above is {most} payments, and its p95 is the slowest one of them. "
                f"Chain inclusion is timed to the block of the paying transaction, read at the commitment level `{latency_stages.COMMITMENT}`, which is the "
                "level the relay waits for; no payment's finality was recorded.", ""]
        if dec:
            out += [f"What was measured locally: {dec['source']}. Machine: {dec['machine']}. That is the time Knos's own code takes to decide; on a "
                    "cluster every read of the chain adds a round trip: four runs of the 0.3.18 command on devnet took 4.3 to 32.6 s each; the 0.3.19 "
                    "command, once on each of 24 real tokens, took a median of 356 ms offline (a new process for each token, so that figure included loading the rules), 854 ms for the chain check and 9.1 s for the whole precheck ([BENCH.md](BENCH.md), \"Decision time\").", ""]
        out += ["What is a target and not a measurement: the last column. No decision has been timed on devnet by a benchmark (four `knos decide` runs on real fund tokens of the 0.3.18 release's public rounds took 4.3 to 32.6 s each over the shared public RPC: a first reading, not a sample), no payment has been carried there by the "
                "0.3.18 relay, and the floor stays above zero: a forge must run a job and sign before there is anything to decide "
                "([RELAY.md](RELAY.md), \"The floor\").", ""]
    if q:
        out += ["### The relay's queue (a local test of the queue, not a benchmark of the service)", "",
                f"`python scripts/queue_drill.py --write` (seed {q['seed']}). **This is a local test of the queue, not an end-to-end service "
                "benchmark**: nothing is signed, no transaction is built, no cluster and no GitHub is asked, and the clock is the test's own. "
                "The chain is a stand-in that keeps one rule, the programs' single-use rule (a token is taken once; a second send is answered "
                "\"already\" and moves nothing). It says how the queue (`src/knos/settle/v2/relayq.py`) behaves, and nothing about seconds on a cluster.", "",
                f"{q['items']:,} entries of {q['lanes']} payers were queued and carried by {q['workers']} workers. One worker was killed after it "
                f"took an entry and before it sent; one entry's confirmation was held for {q['slow_s']:.0f} s of the test's clock while others went on.", "",
                "| Check | Result |", "| --- | --- |",
                f"| Entries done | {q['done']:,} of {q['items']:,} |",
                f"| Entries dead, or left open | {q['dead']}, {q['left_open']} |",
                f"| Sends to the chain | {q['sends']:,} (one an entry) |",
                f"| Entries sent twice | {q['sent_twice']} |",
                f"| Entries the chain took, each once | {q['taken_by_chain']:,} |",
                f"| Entries that left out of order within their payer's lane | {q['out_of_order']} |",
                f"| Workers killed | {q['workers_killed']} |",
                f"| Entries taken again after a lease of {q['lease_s']} s expired | {q['taken_again']} (the killed worker's) |",
                f"| At least {HELD_FOR_SLOW} entries carried while the slow one was in flight | {'yes' if q['others_went_on_while_the_slow_one_was_in_flight'] else 'no'} |", "",
                "What it does not show: a kill between a send and its answer. Then the entry is sent a second time, and it is the program "
                "that refuses the repeat; `tests/test_relayq.py` runs that case against the stand-in, and `tests/test_relay_failures.py` runs "
                "a relay killed between its send and the confirmation on the programs as built (LiteSVM).", ""]
    if sw:
        whole = (st or {}).get("whole") or {}
        made = (f"The {whole['n']} payments recorded on devnet above (public program ids, {_when(st['source'])}: p50 {whole['p50']} s, "
                f"p95 {whole['p95']} s) were made by the serial sweep, "
                "before it was on the queue: no figure on this page times the queue on a cluster.") if whole else \
            "No payment recorded on devnet was carried by the sweep on the queue: no figure on this page times the queue on a cluster."
        out += ["### The always-on sweep on the queue (the same local test, through the relay's own pass)", "",
                "The same command runs a second part: `knos.proof.ghrelay.once`, the pass the public worker repeats every 3 s, which now "
                f"queues what it reads and carries it with the queue's {sw['workers']} workers. **This too is a local test of the queue, not an "
                f"end-to-end benchmark**: GitHub and the chain are stand-ins and the clock is the test's own. {made}", "",
                f"{sw['tokens']} tokens of {sw['owners']} owners were posted; the confirmation of one took {sw['slow_s']:.0f} s of the test's "
                "clock. Then two more were posted, and the pass that carried them was killed after it had sent one and before it noted anything.", "",
                "| Check | Result |", "| --- | --- |",
                f"| Tokens carried in the first pass | {sw['done_in_the_first_pass']} of {sw['tokens']}, with {sw['sends_in_the_first_pass']} sends |",
                f"| Tokens done before the slow one confirmed | {sw['done_before_the_slow_one_confirmed']} of the other {sw['tokens'] - 1} |",
                f"| Seconds from comment to answer on the test's clock: the slow one, the slowest other | {sw['slow_one_took_s']}, {sw['slowest_other_took_s']} |",
                f"| Most tokens in flight at once | {sw['most_in_flight']} |",
                f"| Times two tokens of one owner were in flight together | {sw['two_of_one_owner_in_flight']} |",
                f"| Tokens the chain took out of their owner's order | {sw['out_of_order']} |",
                f"| The killed pass's token: sends, times the chain took it | {sw['killed_token_sends']}, {sw['killed_token_taken_by_chain']} "
                "(the second send was answered \"already\") |",
                f"| Tokens the chain took, and log lines | {sw['taken_by_chain']}, {sw['log_lines']} |", "",
                "What changed after this drill was recorded (0.3.18): a pass reads the comments again every 3 s while a worker still waits for a "
                "confirmation, and a free worker carries what is new, so a comment posted meanwhile no longer waits for the slowest token of the pass "
                "(`tests/test_relay_speed.py`, on a stand-in chain; not measured on a cluster). The pass itself still returns when its last worker has answered.", ""]
    return out


MEASURED_KIND = {"fund": "funding only (FundOrderWallet), no PayOrder", "pay": "end-to-end PayOrder: token verification, then the payment"}
HELD_FOR_SLOW = 20      # scripts/queue_drill.py HELD_FOR: entries carried while the slow one is held


def render_workflow(w: dict, runs: list) -> list[str]:
    """Section 5, from docs/load.json's `workflow` section (scripts/capacity.py writes it): what one order costs outside
    the chain, and which limit a customer meets first."""
    L, c, rel, lat = w["limits"], w["counted"], w["relay"], w["latency"]
    own, pub, m2p = w["budget"]["own"], w["budget"]["public"], lat["merge_to_paid_s"]
    ways = {"own": "the job's own relay", "public": "the public worker"}
    out = ["## 5. The whole workflow", "",
           "A chain rate is not the system's capacity. An order is also two workflow jobs, the requests each makes of GitHub with a token "
           "GitHub rations, the comments it posts, a token GitHub signs, a relay that carries it and a statement someone reads back. This "
           "section counts those and asks which limit a customer meets first. `python scripts/capacity.py --write` wrote it; "
           "`python scripts/capacity.py -R <repositories> -N <deliverables a day>` answers for any customer.", "",
           "### What one word of the workflow asks of GitHub (counted)", "",
           "Counted by running `command`, `settle` and `attest` of `src/knos/flow.py` against the tests' stand-in for api.github.com "
           "(`tests/_flow.py`), on the simplest order: one issue, one pull request, one payee with a bound wallet. It is a count of the "
           "code's requests, exact for that case; an order with more payees, more closing issues or a policy file reads more. It was not "
           "counted on GitHub itself.", "",
           "| Word | Token carried by | Requests read | Requests written | Comments made | Tokens GitHub signs | Jobs |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for way in ("own", "public"):
        for x in c[way].values():
            out.append(f"| {x['word']} | {ways[way]} | {x['reads']} | {x['writes']} | {x['comments']} | {x['tokens_signed']} | {x['jobs']} |")
    out += ["", "The job's own relay is the job sending the transactions itself with a fee key the repository keeps (`KNOS_RELAY_KEY`). "
            "Without the key the token is posted as a comment and the public worker carries it; the job then reads the worker's log every "
            f"{rel['wait_every_s']:g} s for up to {rel['wait_at_most_s']} s. Those reads use the repository's own token and are not "
            "conditional, so each one counts.", "",
            "### The budget of one deliverable (funded by a comment, paid on its merge)", "",
            "| | The job's own relay | The public worker | Where the number is from |", "| --- | --- | --- | --- |",
            f"| Workflow jobs | {own['jobs']} | {pub['jobs']} | counted |",
            f"| GitHub requests with the repository's token, the work itself | {own['reads'] + own['writes']} | {pub['reads'] + pub['writes']} | counted |",
            f"| Reads of the relay log while waiting, at the median wait | 0 | {pub['poll_requests']['median']} | derived: one read every "
            f"{rel['wait_every_s']:g} s for the median of merge-to-paid, {m2p['median']} s |",
            f"| the same at the p95 wait ({m2p['p95']} s) | 0 | {pub['poll_requests']['p95']} | derived |",
            f"| the same when no relay answers ({rel['wait_at_most_s']} s) | 0 | {pub['poll_requests']['timeout']} | derived |",
            f"| Requests in all, at the p95 wait | {own['token_requests']['p95']} | {pub['token_requests']['p95']} | counted + derived |",
            f"| Comments made in the repository | {own['comments']} | {pub['comments']} | counted |",
            f"| Comments the public worker adds to its log | 0 | {pub['relay_log_comments']} | from the code (`ghrelay.once` logs a carried token at once) |",
            f"| Tokens GitHub signs (OIDC) | {own['tokens_signed']} | {pub['tokens_signed']} | counted |",
            f"| Solana transactions | {own['transactions']} | {pub['transactions']} | measured in the simulator (section 2) |",
            f"| Bytes of signed transactions | {own['bytes']:,} | {pub['bytes']:,} | measured in the simulator (p50) |",
            f"| Compute units | {own['cu']:,} | {pub['cu']:,} | measured in the simulator (mean) |",
            f"| Seconds from merge to paid | not timed apart | median {m2p['median']}, p95 {m2p['p95']} | recorded on devnet, public program ids: {m2p['count']} "
            f"payments in the public relay's log, {lat['window']['from']} to {lat['window']['to']} (`docs/bench.json`) |",
            "| Actions minutes | not measured | not measured | a job's time on the runner was not recorded; standard runners are free in "
            "public repositories |",
            "| RPC requests to send the transactions | not measured | not measured | |", "",
            f"Runner queue time: {lat['stage_split']}.", "",
            "What the public worker itself spends: every pass (one every "
            f"{rel['pass_every_s']:g} s) reads at most {rel['repositories_read_per_pass_at_most']} repositories' newest comments, each a "
            "conditional request. GitHub does not count a conditional request it answers 304 when it carries an Authorization header, so a "
            f"pass that finds nothing new costs nothing against the worker's {L['github_token_requests_per_hour']:,} an hour; a repository "
            f"with a new token costs {rel['counted_reads_per_token']} counted read, and the token {rel['log_comments_per_token']} log comment. "
            f"The search for repositories it does not know runs every {rel['search_every_s']} s, under the search limit of "
            f"{L['search_per_minute']} a minute. A pass queues the tokens it reads and carries up to {rel['tokens_at_a_time']} at once, the "
            "tokens of one owner in the order GitHub issued them (section 6).", "",
            "### The meter's statement (derived from the code)", "",
            "`knos statement --meter` recomputes a month from the program's log lines: the month account's history "
            f"{w['meter']['rows_per_history_request']} rows a request, one `getTransaction` for every transaction in it, and the account "
            f"itself. It reads at most {w['meter']['statement_reads_at_most']:,} transactions. Solana's public endpoints take "
            f"{L['rpc_one_method_per_10s']} requests of one method per 10 seconds from one address, and say they are not for production.", "",
            "| Evaluations a day | RPC requests for a 30-day month, one transaction an evaluation | With one batch a day |", "| --- | --- | --- |"]
    for n, x in w["statement_requests"].items():
        out.append(f"| {int(n):,} | {x['one_by_one']:,} | {x['batched_daily']:,} |")
    out += ["", "### Which limit binds first", "",
            "For a customer with R repositories and N accepted deliverables a day, the work spread evenly over the repositories and over "
            "the day (an assumption: a busier hour lowers every figure in proportion; `--peak` sets it). \"Binds at\" is the N at which "
            "the limit is reached; the model is arithmetic on the numbers above and on the published limits, and none of these volumes was run. "
            "\"Binds first\" is among the limits on the work; the meter's statement is a limit on reading the count back, listed in the last column.", "",
            "| Repositories | Deliverables a day | Token carried by | Binds first | Binds at (a day) | This volume fits | Limits this volume is past |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for a in w["customers"]:
        out.append(f"| {a['repositories']:,} | {a['per_day']:,} | {ways[a['way']]} | {a['first']} | {a['at']:,} | {'yes' if a['fits'] else '**no**'} | "
                   f"{'; '.join(a['binding']) or 'none'} |")
    big = {a["way"]: a for a in w["customers"] if a["per_day"] == max(x["per_day"] for x in w["customers"])}
    at = {way: {r["limit"]: r["at"] for r in big[way]["bounds"]} for way in big}
    rows = []                           # a limit that is the same either way is one row; one that differs is a row for each way
    for way in ("own", "public"):
        other = at["public" if way == "own" else "own"]
        for r in big[way]["bounds"]:
            same = other.get(r["limit"]) == r["at"]
            if not (same and way == "public"):
                rows.append((r, "" if same else f" ({ways[way]})"))
    out += ["", f"Every limit, for the largest of the three ({big['own']['repositories']:,} repositories, {big['own']['per_day']:,} a day), soonest first. "
            f"The waits it uses are merge-to-paid over {m2p['count']} payments on the public program ids, {lat['window']['from']} to {lat['window']['to']}:", "",
            "| Limit | Whose | Binds at (a day) | From | What lifts it without a program change |", "| --- | --- | --- | --- | --- |"]
    for r, way in sorted(rows, key=lambda x: x[0]["at"]):
        out.append(f"| {r['limit']}{way} | {r['scope']} | {r['at']:,} | {r['from']} | {r['lift']} |")
    out += ["", "What this says. The public worker is a convenience for small volumes. The reads of its log that a waiting job makes "
            "are what uses up a repository's hourly requests first, and its own two limits are shared by every repository it serves. A "
            "customer past them relays in its own job with its own fee key, which removes the token comment, the polling and both "
            "shared limits at once. After that the limits are GitHub's, per repository and per account, long before they are Solana's. "
            "The one bound here that configuration cannot move is the fee account of the mint; of all of them only a single Balance's "
            "is further away.", "",
            "### Measured, recorded, derived", "",
            "| What | How it is known |", "| --- | --- |",
            "| Compute units, transactions and bytes of an order; paid once, none lost | measured in the local simulator, 1,000 orders (sections 1 and 2) |"]
    for r in runs:
        fails = sum(x["failures"] for x in r["stages"].values())
        out.append(f"| Token verification, funding from a wallet, refund and close on a cluster | measured on {r['cluster']}, {ids_of(r.get('programs'))}, {r['date']}: "
                   f"{r['orders']:,} orders, {fails} failures (section 4). PayOrder, funding from a Balance and the meter were not sent in that run |")
    out += [f"| Seconds from merge to paid | recorded on devnet, {m2p['count']} payments (`docs/bench.json`) |",
            "| Requests, comments, tokens and jobs of a word | counted from the code against a stand-in for GitHub; not observed on GitHub |",
            "| Limits of GitHub and of Solana | published by them, read on " + w["read"] + " (links below); GitHub says its secondary limits "
            "may change without notice, and its page does not say whether the content limit is counted per repository for a workflow's "
            "token, which this page assumes |",
            "| Cluster rates, the relay log polling, statement requests, every \"binds at\" | derived |",
            "| Actions minutes, runner queue time apart from the rest, RPC requests per order, any GitHub limit actually being hit | not measured |", "",
            "Sources: " + "; ".join(f"[{t}]({u})" for t, u in w["sources"].items()) + ".", ""]
    return out


SOURCES = {"Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit": "https://solana.com/upgrades/100m-cu-blocks",
           "Agave's block cost limits (development branch)": "https://github.com/anza-xyz/agave/blob/master/cost-model/src/block_cost_limits.rs",
           "Solana: slots of 400 ms": "https://solana.com/docs/core/transactions/confirmation"}


def load() -> dict:
    doc = json.loads(JSON.read_text(encoding="utf-8")) if JSON.is_file() else {}
    doc.update(_about=ABOUT, limits=LIMITS, sources=SOURCES)
    doc.setdefault("runs", [])
    return doc


def write(doc: dict) -> None:
    JSON.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    DOC.write_text(render(doc), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Many funded orders at once: measured in the simulator, or against a cluster with a test issuer.")
    ap.add_argument("command", nargs="?", choices=("measure",), help="measure: throughput with N relays side by side (--relays, --orders; --simulate here)")
    ap.add_argument("--relays", type=int, default=4, metavar="N", help="measure: relays side by side, each with its own fee payer")
    ap.add_argument("--orders", type=int, default=40, metavar="M", help="measure: orders funded each way (0: only sweep the relays' SOL back)")
    ap.add_argument("--simulate", action="store_true", help="measure: the local simulator; proves the path, gives no rate, writes nothing")
    ap.add_argument("--pay", action="store_true", help="measure: end-to-end PayOrder capacity instead of funding (scripts/load_pay.py: --relays, --orders with --simulate, or --tokens and --wallet)")
    ap.add_argument("--local", type=int, metavar="N", help="N orders through the test builds in LiteSVM")
    ap.add_argument("--devnet", type=int, metavar="N", help="N tokens verified and N orders funded and refunded on a cluster")
    ap.add_argument("--issuer-key", help="the test issuer's RSA private key, PEM (openssl genrsa 2048)")
    ap.add_argument("--issuer-url", default=ISSUER_URL)
    ap.add_argument("--wallet", help="the keypair that pays, registers the key and funds (default: KNOS_WALLET_KEY)")
    ap.add_argument("--rpc", help="the cluster's endpoint (default: KNOS_RPC, else public devnet)")
    ap.add_argument("--senders", type=int, default=8, metavar="K", help="units in flight at once")
    ap.add_argument("--no-refund", action="store_true", help="leave the orders open (they can be refunded after a minute by anyone)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--write", action="store_true", help="write docs/load.json and docs/LOAD.md")
    ap.add_argument("--render", action="store_true", help="only render docs/LOAD.md again from docs/load.json")
    ap.add_argument("--stages", metavar="FILE", help="what `scripts/latency_stages.py --json` printed: store its six stages (docs/load.json `relay.stages`) and render")
    ap.add_argument("--stages-source", metavar="TEXT", help="with --stages: where and when the report was made, in words")
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["measure"] and "--pay" in args:     # end-to-end PayOrder capacity: scripts/load_pay.py
        import load_pay
        rest = [x for x in args[1:] if x not in ("--pay", "--write")]
        if "--write" not in args:
            return load_pay.main(rest)
        if "--simulate" in rest or "--out" in rest:
            ap.error("measure --pay --write records a cluster's run: a simulated run measures nothing and is never written; --out is not needed")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pay.json"
            code = load_pay.main([*rest, "--out", str(out)])
            got = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None
        if got is None:
            return code or 1
        print(json.dumps(got, indent=1))
        if got.get("attempted"):                        # a run that sent nothing has no figure to keep
            doc = load()
            doc.setdefault("measured", []).append(got)
            write(doc)
        return code
    a = ap.parse_args(argv)
    doc = load()
    if a.stages:
        if not a.stages_source:
            ap.error("--stages needs --stages-source: where and when the report was made (the page prints it)")
        r = json.loads(Path(a.stages).read_text(encoding="utf-8"))
        doc.setdefault("relay", {})["stages"] = {"source": a.stages_source, "whole": {k: r["whole"][k] for k in ("n", "p50", "p95")}, "six": r["six"]}
        write(doc)
        return 0
    if a.render:
        write(doc)
        return 0
    if a.command == "measure":
        if a.relays < 1 or a.orders < 0:
            ap.error("measure takes --relays 1 or more and --orders 0 or more")
        if a.simulate:
            if a.write:
                ap.error("a simulated run measures nothing: it is never written")
            from load_sim import SimRpc
            sim = SimRpc()
            got = measure(sim, sim.c.fund(), a.relays, a.orders, name="simulator", say=print,
                          sender=lambda payer: Sender(sim, payer, within=30.0, poll=1.0, clock=sim.clock, sleep=sim.sleep))
            got["note"] = "the local simulator: the path works; its seconds are the script's own clock and say nothing about a cluster"
        else:
            ledger = chain.Ledger(a.rpc) if a.rpc else chain.ledger()
            got = measure(Rpc(ledger.url), chain.wallet(a.wallet), a.relays, a.orders, say=print)
            doc.setdefault("measured", []).append(got)
    elif a.local:
        got = run_local(a.local, a.seed)
        doc["local"] = got
    elif a.devnet:
        if not a.issuer_key:
            ap.error("--devnet needs --issuer-key: the PEM file of the test issuer's RSA private key (make one with `openssl genrsa -out issuer.pem 2048`)")
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(Path(a.issuer_key).read_bytes(), password=None)
        ledger = chain.Ledger(a.rpc) if a.rpc else chain.ledger()
        got = run_devnet(Rpc(ledger.url), chain.wallet(a.wallet), key, a.devnet, a.senders, a.issuer_url, refund=not a.no_refund)
        doc["runs"].append(got)
    else:
        ap.error("say --local N, --devnet N, or measure --relays N --orders M")
    print(json.dumps(got, indent=1))
    if a.write:
        write(doc)
    return 0 if (got.get("invariants") or got).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
